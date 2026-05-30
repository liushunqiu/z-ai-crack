"""OpenAI Chat Completions 适配器。

处理 /v1/chat/completions 请求。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator

from ..models import (
    InternalRequest,
    InternalStreamEvent,
    Message,
    TextDelta,
    ThinkingDelta,
    ToolCallStart,
    ToolCallDelta,
    ToolCallEnd,
    Finish,
    StreamError,
    extract_pass_through,
)
from .base import sse_block, sse_done


def normalize_request(body: dict[str, Any]) -> InternalRequest:
    """将 OpenAI Chat Completions 请求转为 InternalRequest。"""
    messages = []
    for msg in body.get("messages", []):
        messages.append(Message(
            role=msg.get("role", "user"),
            content=msg.get("content", ""),
            name=msg.get("name"),
            tool_call_id=msg.get("tool_call_id"),
        ))

    return InternalRequest(
        model=body.get("model", "GLM-5.1"),
        messages=messages,
        stream=body.get("stream", True),
        tools=body.get("tools"),
        tool_choice=body.get("tool_choice", "auto"),
        conversation_id=body.get("session_id") or body.get("conversation_id"),
        pass_through=extract_pass_through(body),
    )


async def to_sse_stream(
    events: AsyncIterator[InternalStreamEvent],
    model: str,
    request_id: str | None = None,
) -> AsyncIterator[str]:
    """将事件流转为 OpenAI Chat Completions SSE 格式。"""
    if request_id is None:
        request_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

    # 发送 role chunk
    yield sse_block("data", {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant"},
            "finish_reason": None,
        }],
    })

    tool_calls_buffer: dict[int, dict] = {}  # tool_index -> accumulated data

    async for event in events:
        if isinstance(event, TextDelta):
            yield sse_block("data", {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": event.chunk},
                    "finish_reason": None,
                }],
            })

        elif isinstance(event, ThinkingDelta):
            # OpenAI 格式不直接支持 thinking，可以放在 content 前缀或忽略
            # 这里选择忽略，或者可以用自定义字段
            pass

        elif isinstance(event, ToolCallStart):
            tool_calls_buffer[event.tool_index] = {
                "id": event.call_id,
                "type": "function",
                "function": {"name": event.name, "arguments": ""},
            }
            yield sse_block("data", {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": event.tool_index,
                            "id": event.call_id,
                            "type": "function",
                            "function": {"name": event.name, "arguments": ""},
                        }],
                    },
                    "finish_reason": None,
                }],
            })

        elif isinstance(event, ToolCallDelta):
            if event.tool_index in tool_calls_buffer:
                tool_calls_buffer[event.tool_index]["function"]["arguments"] += event.arguments_delta

            yield sse_block("data", {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": event.tool_index,
                            "function": {"arguments": event.arguments_delta},
                        }],
                    },
                    "finish_reason": None,
                }],
            })

        elif isinstance(event, ToolCallEnd):
            pass  # 无需额外处理

        elif isinstance(event, Finish):
            finish_reason = event.reason
            if finish_reason == "tool_calls":
                finish_reason = "tool_calls"
            elif finish_reason == "stop":
                finish_reason = "stop"
            else:
                finish_reason = "stop"

            yield sse_block("data", {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": finish_reason,
                }],
            })

        elif isinstance(event, StreamError):
            yield sse_block("data", {
                "error": {
                    "message": event.message,
                    "type": "server_error",
                    "code": event.code,
                },
            })

    yield sse_done()


def to_non_stream_response(
    text: str,
    model: str,
    request_id: str | None = None,
    finish_reason: str = "stop",
) -> dict[str, Any]:
    """将文本转为非流式响应。"""
    if request_id is None:
        request_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": text,
            },
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
