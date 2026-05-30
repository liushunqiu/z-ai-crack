"""Prompt 兼容层: 将 OpenAI messages 拍平为 Z.ai 可接受的 prompt 字符串。

Z.ai API 接受单个 prompt 字符串，所以需要将 OpenAI 的 messages 数组
（包含 system、user、assistant、tool 等角色）拍平为一个字符串。

设计:
- 首次请求(first_turn=True):拼 [system 文本] + [工具定义说明] + [历史消息] + [最新 user]
- 续轮请求(first_turn=False):只发自上次 assistant 之后新增的消息
   (一般是 function_call_output + 可选的新 user 消息),
   前缀 [TOOL RESULTS] 让模型知道是工具执行结果回填。
"""
from __future__ import annotations

from .models import InternalRequest, Message


def flatten_to_prompt(req: InternalRequest, *, first_turn: bool) -> str:
    if first_turn:
        return _flatten_first_turn(req)
    return _flatten_continuation(req)


def _flatten_first_turn(req: InternalRequest) -> str:
    system_parts: list[str] = []
    history_parts: list[str] = []
    latest_user: str | None = None

    msgs = list(req.messages)
    last_user_idx = _last_index(msgs, lambda m: m.role == "user")

    for i, msg in enumerate(msgs):
        if msg.role == "system":
            if msg.content:
                system_parts.append(msg.content)
            continue
        if i == last_user_idx and msg.role == "user":
            latest_user = msg.content or ""
            continue
        history_parts.append(_format_history_message(msg))

    blocks: list[str] = []
    system_text = "\n\n".join(p for p in system_parts if p).strip()
    if req.tools:
        from .dsml import format_tools_section
        tools_block = format_tools_section(req.tools).strip()
    else:
        tools_block = ""
    if system_text or tools_block:
        merged = "\n\n".join(p for p in (system_text, tools_block) if p)
        blocks.append("[SYSTEM]\n" + merged + "\n[/SYSTEM]")

    if history_parts:
        blocks.append("[HISTORY]\n" + "\n\n".join(history_parts) + "\n[/HISTORY]")

    if latest_user is not None:
        blocks.append(latest_user)
    elif not history_parts:
        blocks.append("")

    return "\n\n".join(blocks).strip()


def _flatten_continuation(req: InternalRequest) -> str:
    """续轮: 把"上一次 assistant 之后"的所有消息渲染发出去。

    Codex/客户端的协议总是把整个历史发回来,
    所以只取末尾的 tool / user 消息。
    """
    tail: list[Message] = []
    for msg in reversed(req.messages):
        if msg.role == "assistant":
            break
        tail.append(msg)
    tail.reverse()

    if not tail:
        last_user = next(
            (m for m in reversed(req.messages) if m.role == "user"), None
        )
        return last_user.content if last_user and last_user.content else ""

    blocks: list[str] = []
    tool_outputs: list[Message] = []
    user_followups: list[Message] = []
    for msg in tail:
        if msg.role == "tool":
            tool_outputs.append(msg)
        elif msg.role == "user":
            user_followups.append(msg)

    if tool_outputs:
        block = "[TOOL RESULTS]\n" + "\n\n".join(
            _format_tool_output(m) for m in tool_outputs
        ) + "\n[/TOOL RESULTS]"
        blocks.append(block)
        if not user_followups:
            blocks.append(_CONTINUATION_HINT)
    for m in user_followups:
        if m.content:
            blocks.append(m.content)

    return "\n\n".join(blocks).strip()


_CONTINUATION_HINT = (
    "工具已执行完成,结果见上方 [TOOL RESULTS]。请直接基于结果继续推进任务:\n"
    "- 如果还有未完成的步骤,立刻发起下一个 "
    "<|DSML|tool_calls> 调用执行下一步。\n"
    "- 不要复述工具结果,不要把计划/状态再用自然语言描述一遍,不要询问用户是否继续。\n"
    "- 仅当整个任务已完成、或必须由用户补充信息才能继续时,才用自然语言回复。\n"
    "- 继续调用工具时,你的回复必须以 <|DSML|tool_calls> 开头,不要在前面加任何文字。"
)


def _format_history_message(msg: Message) -> str:
    role = msg.role
    if role == "assistant":
        return f"[ASSISTANT]\n{msg.content}\n[/ASSISTANT]"
    if role == "tool":
        return _format_tool_output(msg)
    if role == "user":
        return f"[USER]\n{msg.content}\n[/USER]"
    return f"[{role.upper()}]\n{msg.content}\n[/{role.upper()}]"


def _format_tool_output(msg: Message) -> str:
    """渲染单个 tool 结果块。

    带上 name / call_id 属性以便模型在并行调用、多轮场景里能对应回哪个 invoke。
    content 为空时给一个明确占位。
    """
    attrs = []
    if msg.name:
        attrs.append(f'name="{_attr(msg.name)}"')
    if msg.tool_call_id:
        attrs.append(f'call_id="{_attr(msg.tool_call_id)}"')
    attr_str = (" " + " ".join(attrs)) if attrs else ""
    body = msg.content.strip() if msg.content else ""
    if not body:
        body = "(tool executed successfully, no output)"
    return f"[TOOL OUTPUT{attr_str}]\n{body}\n[/TOOL OUTPUT]"


def _attr(text: str) -> str:
    return text.replace("&", "&amp;").replace('"', "&quot;")


def _last_index(seq: list, predicate) -> int:
    for i in range(len(seq) - 1, -1, -1):
        if predicate(seq[i]):
            return i
    return -1
