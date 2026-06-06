"""OpenAI Responses API 适配器(Codex 的 wire_api=responses 走这里)。

工具调用纠错:
- 工具名:Z.ai 可能输出 'bash' 而 Codex 定义 'Bash' -> 建大小写映射
- 参数名:Z.ai 可能输出 'command' 而 schema 是 'cmd' -> 建别名映射
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator

from ..dsml import tool_calls_to_dsml
from ..models import (
    Finish,
    InternalRequest,
    InternalStreamEvent,
    Message,
    StreamError,
    TextDelta,
    ThinkingDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
    extract_pass_through,
)
from .base import sse_block, sse_block_or_done, sse_done


def normalize_request(body: dict) -> InternalRequest:
    model = body.get("model") or "GLM-5.1"
    tool_choice = body.get("tool_choice") or "auto"
    # 优先 previous_response_id,其次 conversation_id
    conv_id = body.get("previous_response_id") or body.get("conversation_id")
    messages = _extract_input_messages(body)
    tools = body.get("tools")
    if tools is not None and not isinstance(tools, list):
        tools = None
    return InternalRequest(
        model=model,
        messages=messages,
        stream=True,
        tools=tools,
        tool_choice=tool_choice if isinstance(tool_choice, str) else "auto",
        conversation_id=conv_id,
        pass_through=extract_pass_through(body),
    )


def _extract_input_messages(body: dict) -> list[Message]:
    inp = body.get("input")
    msgs: list[Message] = []
    if isinstance(inp, str):
        msgs.append(Message("user", inp))
        return msgs
    if not isinstance(inp, list):
        return msgs

    # call_id -> 工具名:codex 的 function_call_output 只带 call_id 不带 name,
    # 需要从同一次请求里前面出现的 function_call 节点反查。
    call_id_to_name: dict[str, str] = {}

    for node in inp:
        if not isinstance(node, dict):
            continue
        role = node.get("role") or ""
        typ = node.get("type") or ""

        if typ in ("function_call", "tool_call"):
            name = (node.get("name") or "").strip()
            args = node.get("arguments")
            if args is None:
                args = node.get("input")
            if args is None:
                args_str = "{}"
            elif isinstance(args, str):
                args_str = args or "{}"
            else:
                args_str = json.dumps(args, ensure_ascii=False)
            call_id = node.get("call_id") or node.get("id") or ""
            if not name:
                continue
            if call_id:
                call_id_to_name[call_id] = name
            tc = [{
                "id": call_id, "type": "function",
                "function": {"name": name, "arguments": args_str},
            }]
            msgs.append(Message("assistant", tool_calls_to_dsml(tc)))
            continue

        if typ in ("function_call_output", "tool_result"):
            output = node.get("output")
            if output is None:
                output = node.get("content") or ""
            if isinstance(output, list):
                # Codex 可能把 output 包成 [{type:..., text:...}, ...]
                buf: list[str] = []
                for part in output:
                    if isinstance(part, dict):
                        text = part.get("text") or part.get("content") or ""
                        buf.append(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False))
                output = "\n".join(buf)
            elif not isinstance(output, str):
                output = json.dumps(output, ensure_ascii=False)
            call_id = node.get("call_id") or node.get("tool_call_id") or node.get("id") or ""
            tool_name = call_id_to_name.get(call_id) if call_id else None
            msgs.append(Message("tool", output, name=tool_name, tool_call_id=call_id or None))
            continue

        if typ in ("reasoning",):
            # Codex 历史里的 reasoning 不回灌给模型(成本上没意义)
            continue

        # message / 空 type:正常消息
        msg_role = role or "user"
        content_node = node.get("content")
        if isinstance(content_node, str):
            msgs.append(Message(msg_role, content_node))
        elif isinstance(content_node, list):
            buf: list[str] = []
            for part in content_node:
                if not isinstance(part, dict):
                    continue
                pt = part.get("type") or ""
                if pt in ("input_text", "output_text", "text"):
                    text = part.get("text") or ""
                    if text:
                        buf.append(text)
            if buf:
                msgs.append(Message(msg_role, "\n".join(buf)))
    return msgs


# ──────────────────────────────────────────────────────────────
# 工具名/参数名纠错(照搬 Java buildToolNameCaseMap / buildToolParamNameMap)
# ──────────────────────────────────────────────────────────────

def _extract_tool_name(tool: dict) -> str:
    n = (tool.get("name") or "").strip()
    if n:
        return n
    func = tool.get("function") or {}
    return (func.get("name") or "").strip()


def _extract_tool_props(tool: dict) -> dict | None:
    for k in ("parameters", "input_schema", "inputSchema", "schema"):
        schema = tool.get(k)
        if isinstance(schema, dict):
            props = schema.get("properties")
            if isinstance(props, dict):
                return props
    func = tool.get("function") or {}
    for k in ("parameters", "input_schema", "inputSchema", "schema"):
        schema = func.get(k)
        if isinstance(schema, dict):
            props = schema.get("properties")
            if isinstance(props, dict):
                return props
    return None


def _build_tool_name_case_map(tools: list[dict] | None) -> dict[str, str]:
    """lowercase name -> original name,外加常见别名(bash/shell/...)。"""
    name_map: dict[str, str] = {}
    if not tools:
        return name_map
    original_names: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = _extract_tool_name(tool)
        if name:
            name_map[name.lower()] = name
            original_names.append(name)

    exec_tool = None
    for name in original_names:
        low = name.lower()
        if any(k in low for k in ("exec", "command", "bash", "shell", "run")):
            exec_tool = name
            break

    for name in original_names:
        low = name.lower()
        if any(k in low for k in ("exec", "command", "bash", "shell", "run")):
            for alias in ("bash", "shell", "terminal", "run", "execute", "cmd"):
                name_map.setdefault(alias, name)
        if any(k in low for k in ("read", "file", "view", "open", "cat")):
            for alias in ("read_file", "readfile", "open_file", "cat", "read"):
                name_map.setdefault(alias, name)
        if any(k in low for k in ("list", "dir", "ls", "glob", "find")):
            for alias in ("list_files", "listfiles", "ls", "find", "glob", "list"):
                name_map.setdefault(alias, name)
        if any(k in low for k in ("write", "save", "create")):
            for alias in ("write_file", "writefile", "save_file", "create_file",
                          "write", "write_stdin"):
                name_map.setdefault(alias, name)
        if any(k in low for k in ("edit", "patch", "modify", "update")):
            for alias in ("edit_file", "apply_patch", "patch", "edit"):
                name_map.setdefault(alias, name)
        if any(k in low for k in ("search", "grep", "find_text")):
            for alias in ("search", "grep", "search_files"):
                name_map.setdefault(alias, name)

    if exec_tool:
        name_map["__default__"] = exec_tool
    return name_map


def _build_tool_param_name_map(tools: list[dict] | None) -> dict[str, dict[str, str]]:
    """tool_name -> {alias_param_name(lower) -> actual_param_name}"""
    result: dict[str, dict[str, str]] = {}
    if not tools:
        return result
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = _extract_tool_name(tool)
        if not name:
            continue
        props = _extract_tool_props(tool)
        if not props:
            continue
        actual = list(props.keys())
        pmap: dict[str, str] = {}
        for p in actual:
            low = p.lower()
            pmap[low] = p
            if low == "cmd":
                pmap["command"] = p
            elif low == "command":
                pmap["cmd"] = p
            if low in ("file_path", "filepath"):
                pmap["path"] = p
                pmap["file"] = p
            elif low == "path":
                pmap["file_path"] = p
                pmap["filepath"] = p
            if low == "content":
                pmap["text"] = p
                pmap["data"] = p
                pmap["body"] = p
            elif low == "text":
                pmap["content"] = p
                pmap["data"] = p
            if low == "description":
                pmap["desc"] = p
            elif low == "desc":
                pmap["description"] = p
        if pmap:
            result[name] = pmap
            result[name.lower()] = pmap
    return result


def _fix_param_names(
    tool_name: str | None,
    args_json: str,
    param_map: dict[str, dict[str, str]],
) -> str:
    if not tool_name or not args_json:
        return args_json
    pmap = param_map.get(tool_name) or param_map.get(tool_name.lower())
    if not pmap:
        return args_json
    try:
        parsed = json.loads(args_json)
    except (json.JSONDecodeError, ValueError):
        return args_json
    if not isinstance(parsed, dict):
        return args_json
    fixed: dict = {}
    changed = False
    for k, v in parsed.items():
        mapped = pmap.get(k.lower())
        if mapped and mapped != k:
            fixed[mapped] = v
            changed = True
        else:
            fixed[k] = v
    return json.dumps(fixed, ensure_ascii=False) if changed else args_json


# ──────────────────────────────────────────────────────────────
# 文件内容净化: 去掉 shell heredoc / echo / printf 包装
# ──────────────────────────────────────────────────────────────

# 写文件工具名集合 (小写)
_WRITE_TOOLS_LOWER = frozenset({
    "write", "write_file", "write_to_file", "write_stdin",
    "create_file", "save_file",
})

# Edit 工具名集合 (小写)
_EDIT_TOOLS_LOWER = frozenset({
    "edit", "edit_file", "apply_patch", "patch", "modify",
})

# 命令执行工具名集合 (小写) - 可能用于写文件
_EXEC_TOOLS_LOWER = frozenset({
    "exec_command", "execute_command", "bash", "shell",
    "run", "execute", "cmd", "terminal",
})

# Heredoc 提取正则 (支持多种变体)
_HEREDOC_PATTERNS = [
    # cat > FILE << 'TAG' ... TAG (重定向在前)
    re.compile(r"cat\s*>\s*\S+\s*<<\s*['\"]?(\w+)['\"]?\s*\n([\s\S]*?)\n\1\s*$", re.MULTILINE),
    # cat << 'TAG' > FILE ... TAG (重定向在后)
    re.compile(r"cat\s*<<\s*['\"]?(\w+)['\"]?\s*>\s*\S+\s*\n([\s\S]*?)\n\1\s*$", re.MULTILINE),
    # cat << 'TAG' >> FILE ... TAG (追加重定向)
    re.compile(r"cat\s*<<\s*['\"]?(\w+)['\"]?\s*>>\s*\S+\s*\n([\s\S]*?)\n\1\s*$", re.MULTILINE),
    # tee FILE << 'TAG' ... TAG
    re.compile(r"tee\s+\S+\s*<<\s*['\"]?(\w+)['\"]?\s*\n([\s\S]*?)\n\1\s*$", re.MULTILINE),
]

_ECHO_PATTERNS = [
    # echo "content" > FILE
    re.compile(r"^echo\s+['\"](.*)['\"]\s*>\s*\S+$", re.DOTALL),
    # echo "content" >> FILE
    re.compile(r"^echo\s+['\"](.*)['\"]\s*>>\s*\S+$", re.DOTALL),
]

_PRINTF_PATTERNS = [
    # printf "content" > FILE
    re.compile(r"^printf\s+['\"](.*)['\"]\s*>\s*\S+$", re.DOTALL),
    # printf "content" >> FILE
    re.compile(r"^printf\s+['\"](.*)['\"]\s*>>\s*\S+$", re.DOTALL),
]


def _extract_pure_content(value: str) -> str:
    """从 shell heredoc / echo / printf 包装中提取纯文件内容。

    处理 Z.ai 模型经常返回的 shell 命令格式，提取实际内容。
    """
    if not value:
        return value
    trimmed = value.strip()
    if not trimmed:
        return value

    # 尝试 heredoc 提取
    for pattern in _HEREDOC_PATTERNS:
        m = pattern.search(trimmed)
        if m:
            return m.group(2)

    # 尝试 echo 提取
    for pattern in _ECHO_PATTERNS:
        m = pattern.match(trimmed)
        if m:
            return m.group(1)

    # 尝试 printf 提取
    for pattern in _PRINTF_PATTERNS:
        m = pattern.match(trimmed)
        if m:
            return m.group(1)

    return value


def _purify_file_content_args(tool_name: str, args_json: str) -> str:
    """对写文件工具的参数做净化，去掉 shell 包装。

    只处理 content 参数，确保返回纯文件内容。
    """
    if not tool_name or not args_json:
        return args_json

    # 检查是否是需要净化的工具
    name_lower = tool_name.lower()
    is_write = name_lower in _WRITE_TOOLS_LOWER
    is_edit = name_lower in _EDIT_TOOLS_LOWER

    if not is_write and not is_edit:
        return args_json

    try:
        parsed = json.loads(args_json)
    except (json.JSONDecodeError, ValueError):
        return args_json
    if not isinstance(parsed, dict):
        return args_json

    changed = False

    # 净化 Write 工具的 content 参数
    if is_write and "content" in parsed:
        original = parsed["content"]
        if isinstance(original, str):
            purified = _extract_pure_content(original)
            if purified != original:
                parsed["content"] = purified
                changed = True

    # 净化 Edit 工具的 new_string 参数
    if is_edit and "new_string" in parsed:
        original = parsed["new_string"]
        if isinstance(original, str):
            purified = _extract_pure_content(original)
            if purified != original:
                parsed["new_string"] = purified
                changed = True

    return json.dumps(parsed, ensure_ascii=False) if changed else args_json


def _extract_file_write_info(command: str) -> tuple[str, str] | None:
    """检测命令是否是文件写入操作，返回 (file_path, content) 或 None。

    支持的格式：
    - cat > FILE << 'TAG' ... TAG
    - cat << 'TAG' > FILE ... TAG
    - tee FILE << 'TAG' ... TAG
    - echo "content" > FILE
    - printf "content" > FILE
    """
    if not command:
        return None
    trimmed = command.strip()

    # Heredoc 格式
    for pattern in _HEREDOC_PATTERNS:
        m = pattern.search(trimmed)
        if m:
            # 从命令中提取文件路径
            # cat > FILE << 'TAG' -> FILE
            # cat << 'TAG' > FILE -> FILE
            # tee FILE << 'TAG' -> FILE
            file_path_match = re.search(r'(?:cat\s*>\s*|>\s*|tee\s+)(\S+)', trimmed)
            if file_path_match:
                return (file_path_match.group(1), m.group(2))

    # echo 格式
    for pattern in _ECHO_PATTERNS:
        m = pattern.match(trimmed)
        if m:
            file_path_match = re.search(r'>\s*(\S+)', trimmed)
            if file_path_match:
                return (file_path_match.group(1), m.group(1))

    # printf 格式
    for pattern in _PRINTF_PATTERNS:
        m = pattern.match(trimmed)
        if m:
            file_path_match = re.search(r'>\s*(\S+)', trimmed)
            if file_path_match:
                return (file_path_match.group(1), m.group(1))

    return None


def _purify_exec_command_args(tool_name: str, args_json: str) -> str:
    """对命令执行工具的参数做净化。

    如果参数是文件写入操作（cat > FILE << 'TAG' ... TAG 等），
    转换为 Write 工具的格式 {file_path, content}。
    """
    if not tool_name or not args_json:
        return args_json

    name_lower = tool_name.lower()
    if name_lower not in _EXEC_TOOLS_LOWER:
        return args_json

    try:
        parsed = json.loads(args_json)
    except (json.JSONDecodeError, ValueError):
        return args_json
    if not isinstance(parsed, dict):
        return args_json

    # 获取命令参数
    command = parsed.get("command") or parsed.get("cmd") or ""
    if not command or not isinstance(command, str):
        return args_json

    # 检测是否是文件写入操作
    file_info = _extract_file_write_info(command)
    if not file_info:
        return args_json

    file_path, content = file_info

    # 转换为 Write 工具格式
    return json.dumps({
        "file_path": file_path,
        "content": content,
    }, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────
# 状态机 + SSE 生成
# ──────────────────────────────────────────────────────────────

class _ResponsesState:
    def __init__(self) -> None:
        self.text_item_created = False
        self.reasoning_item_created = False
        self.reasoning_item_closed = False
        self.accumulated_text: list[str] = []
        self.accumulated_reasoning: list[str] = []
        self.active_tools: dict[str, dict] = {}  # call_id -> {name, args}
        self.tool_count = 0

    @property
    def accumulated_text_str(self) -> str:
        return "".join(self.accumulated_text)

    @property
    def accumulated_reasoning_str(self) -> str:
        return "".join(self.accumulated_reasoning)

    def has_any_tool(self) -> bool:
        return self.tool_count > 0


async def to_sse(
    events: AsyncIterator[InternalStreamEvent],
    request: InternalRequest,
    response_id: str,
    *,
    on_complete=None,
) -> AsyncIterator[str]:
    """把 InternalStreamEvent 流转成 OpenAI Responses SSE 文本块。

    on_complete(buffer: list[InternalStreamEvent]) 可选,在 done 之前被回调,
    用于缓存完整 response 以供 GET /v1/responses/{id} 取回。
    """
    created_at = int(time.time())
    name_map = _build_tool_name_case_map(request.tools)
    param_map = _build_tool_param_name_map(request.tools)
    state = _ResponsesState()
    buffered: list[InternalStreamEvent] = []

    yield sse_block("response.created", {
        "type": "response.created",
        "response": {
            "id": response_id,
            "object": "response",
            "status": "in_progress",
            "created_at": created_at,
            "model": request.model,
        },
    })

    try:
        async for event in events:
            buffered.append(event)
            async for chunk in _convert_event(event, response_id, state, name_map, param_map):
                yield chunk
    except Exception as e:
        yield sse_block("response.failed", {
            "type": "response.failed",
            "response_id": response_id,
            "error": {"message": str(e), "code": 500},
        })
        yield sse_done()
        return

    # 收尾
    is_required = request.tool_choice and request.tool_choice.lower() == "required"
    if is_required and not state.has_any_tool():
        yield sse_block("response.failed", {
            "type": "response.failed",
            "response_id": response_id,
            "error": {
                "message": "tool_choice=required but no tool call was generated",
                "code": 422,
            },
        })
        yield sse_done()
        return

    # reasoning 没关 -> 关掉
    if state.reasoning_item_created and not state.reasoning_item_closed:
        final = state.accumulated_reasoning_str
        yield sse_block("response.reasoning_summary_text.done", {
            "type": "response.reasoning_summary_text.done",
            "item_id": "reasoning_0",
            "response_id": response_id,
            "output_index": 0,
            "summary_index": 0,
            "text": final,
        })
        yield sse_block("response.output_item.done", {
            "type": "response.output_item.done",
            "item_id": "reasoning_0",
            "response_id": response_id,
            "output_index": 0,
            "item": {
                "type": "reasoning",
                "id": "reasoning_0",
                "status": "completed",
                "summary": [{"type": "summary_text", "text": final}],
            },
        })
        state.reasoning_item_closed = True

    # text item 没关 -> 关掉
    if state.text_item_created:
        final_text = state.accumulated_text_str
        text_idx = 1 if state.reasoning_item_created else 0
        yield sse_block("response.output_text.done", {
            "type": "response.output_text.done",
            "item_id": "msg_0",
            "response_id": response_id,
            "output_index": text_idx,
            "content_index": 0,
            "text": final_text,
        })
        yield sse_block("response.content_part.done", {
            "type": "response.content_part.done",
            "item_id": "msg_0",
            "response_id": response_id,
            "output_index": text_idx,
            "content_index": 0,
            "part": {"type": "output_text", "text": final_text},
        })
        yield sse_block("response.output_item.done", {
            "type": "response.output_item.done",
            "item_id": "msg_0",
            "response_id": response_id,
            "output_index": text_idx,
            "item": {
                "type": "message", "id": "msg_0", "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": final_text}],
            },
        })

    yield sse_block("response.completed", {
        "type": "response.completed",
        "response_id": response_id,
        "response": {
            "id": response_id, "object": "response",
            "status": "completed", "model": request.model,
        },
    })
    # [DONE] 哨兵
    yield sse_done()

    if on_complete:
        try:
            on_complete(buffered)
        except Exception:
            pass


async def _convert_event(
    event: InternalStreamEvent,
    response_id: str,
    state: _ResponsesState,
    name_map: dict[str, str],
    param_map: dict[str, dict[str, str]],
) -> AsyncIterator[str]:
    if isinstance(event, ThinkingDelta):
        if not state.reasoning_item_created:
            yield sse_block("response.output_item.added", {
                "type": "response.output_item.added",
                "item_id": "reasoning_0",
                "response_id": response_id,
                "output_index": 0,
                "item": {"type": "reasoning", "status": "in_progress"},
            })
            state.reasoning_item_created = True
        state.accumulated_reasoning.append(event.chunk)
        yield sse_block("response.reasoning_summary_text.delta", {
            "type": "response.reasoning_summary_text.delta",
            "item_id": "reasoning_0",
            "response_id": response_id,
            "output_index": 0,
            "summary_index": 0,
            "delta": event.chunk,
        })
        return

    if isinstance(event, TextDelta):
        # reasoning 还没关 -> 先关
        if state.reasoning_item_created and not state.reasoning_item_closed:
            final = state.accumulated_reasoning_str
            yield sse_block("response.reasoning_summary_text.done", {
                "type": "response.reasoning_summary_text.done",
                "item_id": "reasoning_0",
                "response_id": response_id,
                "output_index": 0,
                "summary_index": 0,
                "text": final,
            })
            yield sse_block("response.output_item.done", {
                "type": "response.output_item.done",
                "item_id": "reasoning_0",
                "response_id": response_id,
                "output_index": 0,
                "item": {
                    "type": "reasoning", "id": "reasoning_0", "status": "completed",
                    "summary": [{"type": "summary_text", "text": final}],
                },
            })
            state.reasoning_item_closed = True

        if not state.text_item_created:
            text_idx = 1 if state.reasoning_item_created else 0
            yield sse_block("response.output_item.added", {
                "type": "response.output_item.added",
                "item_id": "msg_0",
                "response_id": response_id,
                "output_index": text_idx,
                "item": {"type": "message", "role": "assistant", "status": "in_progress"},
            })
            yield sse_block("response.content_part.added", {
                "type": "response.content_part.added",
                "item_id": "msg_0",
                "response_id": response_id,
                "output_index": text_idx,
                "content_index": 0,
                "part": {"type": "output_text", "text": ""},
            })
            state.text_item_created = True

        text_idx = 1 if state.reasoning_item_created else 0
        state.accumulated_text.append(event.chunk)
        yield sse_block("response.output_text.delta", {
            "type": "response.output_text.delta",
            "item_id": "msg_0",
            "response_id": response_id,
            "output_index": text_idx,
            "content_index": 0,
            "delta": event.chunk,
        })
        return

    if isinstance(event, ToolCallStart):
        # 关闭未完成的 reasoning item
        if state.reasoning_item_created and not state.reasoning_item_closed:
            final = state.accumulated_reasoning_str
            yield sse_block("response.reasoning_summary_text.done", {
                "type": "response.reasoning_summary_text.done",
                "item_id": "reasoning_0",
                "response_id": response_id,
                "output_index": 0,
                "summary_index": 0,
                "text": final,
            })
            yield sse_block("response.output_item.done", {
                "type": "response.output_item.done",
                "item_id": "reasoning_0",
                "response_id": response_id,
                "output_index": 0,
                "item": {
                    "type": "reasoning", "id": "reasoning_0", "status": "completed",
                    "summary": [{"type": "summary_text", "text": final}],
                },
            })
            state.reasoning_item_closed = True
        # 关闭未完成的 text item
        if state.text_item_created:
            final_text = state.accumulated_text_str
            text_idx = 1 if state.reasoning_item_created else 0
            yield sse_block("response.output_text.done", {
                "type": "response.output_text.done",
                "item_id": "msg_0",
                "response_id": response_id,
                "output_index": text_idx,
                "content_index": 0,
                "text": final_text,
            })
            yield sse_block("response.content_part.done", {
                "type": "response.content_part.done",
                "item_id": "msg_0",
                "response_id": response_id,
                "output_index": text_idx,
                "content_index": 0,
                "part": {"type": "output_text", "text": final_text},
            })
            yield sse_block("response.output_item.done", {
                "type": "response.output_item.done",
                "item_id": "msg_0",
                "response_id": response_id,
                "output_index": text_idx,
                "item": {
                    "type": "message", "id": "msg_0", "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": final_text}],
                },
            })
            state.text_item_created = False  # 标记已关闭，收尾阶段不再重复关闭
        deepseek_name = event.name
        original = name_map.get(deepseek_name.lower())
        if original is None:
            original = name_map.get("__default__", deepseek_name)
        state.active_tools[event.call_id] = {"name": original, "args": ""}
        state.tool_count += 1
        yield sse_block("response.output_item.added", {
            "type": "response.output_item.added",
            "item_id": event.call_id,
            "response_id": response_id,
            "item": {
                "type": "function_call",
                "id": event.call_id,
                "call_id": event.call_id,
                "name": original,
                "status": "in_progress",
            },
        })
        return

    if isinstance(event, ToolCallDelta):
        entry = state.active_tools.get(event.call_id)
        if not entry:
            return
        fixed = _fix_param_names(entry["name"], event.arguments_delta, param_map)
        entry["args"] += fixed
        yield sse_block("response.function_call_arguments.delta", {
            "type": "response.function_call_arguments.delta",
            "item_id": event.call_id,
            "response_id": response_id,
            "delta": fixed,
        })
        return

    if isinstance(event, ToolCallEnd):
        entry = state.active_tools.get(event.call_id)
        if not entry:
            return
        args = entry["args"] or "{}"
        name = entry["name"] or ""

        # 对写文件工具的参数做净化，去掉 shell heredoc / echo / printf 包装
        args = _purify_file_content_args(name, args)

        # 对命令执行工具的参数做净化，如果检测到文件写入操作则转换为 Write 格式
        purified_exec_args = _purify_exec_command_args(name, args)
        if purified_exec_args != args:
            args = purified_exec_args
            # 检测到文件写入操作，将工具名改为 Write
            name_lower = name.lower()
            if name_lower in _EXEC_TOOLS_LOWER:
                # 从 args 中提取新的工具名
                try:
                    parsed_args = json.loads(args)
                    if "file_path" in parsed_args and "content" in parsed_args:
                        name = "Write"
                except (json.JSONDecodeError, ValueError):
                    pass

        yield sse_block("response.function_call_arguments.done", {
            "type": "response.function_call_arguments.done",
            "item_id": event.call_id,
            "response_id": response_id,
            "call_id": event.call_id,
            "name": name,
            "arguments": args,
        })
        yield sse_block("response.output_item.done", {
            "type": "response.output_item.done",
            "item_id": event.call_id,
            "response_id": response_id,
            "item": {
                "type": "function_call",
                "id": event.call_id,
                "call_id": event.call_id,
                "name": name,
                "arguments": args,
                "status": "completed",
            },
        })
        return

    if isinstance(event, StreamError):
        yield sse_block("response.failed", {
            "type": "response.failed",
            "response_id": response_id,
            "error": {"message": event.message, "code": event.code},
        })
        return

    # Finish / SessionCreated:由外层处理或跳过
    return
