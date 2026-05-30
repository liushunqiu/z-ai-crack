"""统一请求/事件模型。

复用 deepseek-bridge 的 InternalRequest + InternalStreamEvent 设计。
所有协议适配器在这一层握手：OpenAI Chat / Codex Responses 各自 normalize
出 InternalRequest，Z.ai 上游 SSE 解析出 InternalStreamEvent 流。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Union

DEFAULT_MODEL = "GLM-5.1"

# 透传给上游的参数白名单
_PASS_THROUGH_KEYS = (
    "temperature", "top_p", "max_tokens", "frequency_penalty",
    "presence_penalty", "stop", "n", "logprobs", "top_logprobs",
)


@dataclass(frozen=True)
class Message:
    role: str       # user / assistant / system / tool
    content: str    # 工具结果消息也存这里(纯文本)
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class InternalRequest:
    model: str
    messages: list[Message]
    stream: bool = True
    tools: list[dict] | None = None
    tool_choice: str = "auto"            # auto / required / none
    conversation_id: str | None = None   # session_id 用于会话复用
    pass_through: dict = field(default_factory=dict)

    def with_model(self, new_model: str) -> "InternalRequest":
        return replace(self, model=new_model)

    def with_messages(self, new_messages: list[Message]) -> "InternalRequest":
        return replace(self, messages=new_messages)

    def with_conversation_id(self, conv_id: str | None) -> "InternalRequest":
        return replace(self, conversation_id=conv_id)


def extract_pass_through(body: dict) -> dict:
    out: dict = {}
    for k in _PASS_THROUGH_KEYS:
        if k in body and body[k] is not None:
            out[k] = body[k]
    return out


# ──────────────────────────────────────────────────────────────
# 流事件
# ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SessionCreated:
    session_id: str


@dataclass(frozen=True)
class TextDelta:
    chunk: str


@dataclass(frozen=True)
class ThinkingDelta:
    chunk: str


@dataclass(frozen=True)
class ToolCallStart:
    call_id: str
    name: str
    tool_index: int


@dataclass(frozen=True)
class ToolCallDelta:
    call_id: str
    tool_index: int
    arguments_delta: str


@dataclass(frozen=True)
class ToolCallEnd:
    call_id: str
    tool_index: int


@dataclass(frozen=True)
class Finish:
    reason: str          # stop / tool_calls / length / content_filter


@dataclass(frozen=True)
class StreamError:
    message: str
    code: int = 500


InternalStreamEvent = Union[
    SessionCreated, TextDelta, ThinkingDelta,
    ToolCallStart, ToolCallDelta, ToolCallEnd,
    Finish, StreamError,
]
