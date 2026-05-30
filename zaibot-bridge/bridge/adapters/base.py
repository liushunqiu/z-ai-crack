"""SSE 格式化工具。"""
from __future__ import annotations

import json
from typing import Any


def sse_block(event: str, data: dict[str, Any] | str) -> str:
    """格式化 SSE 事件块。"""
    if isinstance(data, dict):
        data_str = json.dumps(data, ensure_ascii=False)
    else:
        data_str = data
    return f"event: {event}\ndata: {data_str}\n\n"


def sse_done() -> str:
    """SSE 结束标记。"""
    return "data: [DONE]\n\n"


def sse_block_or_done(event: str | None, data: dict[str, Any] | str) -> str:
    """格式化 SSE 事件块，如果 event 为 None 则返回 [DONE] 标记。"""
    if event is None:
        return sse_done()
    return sse_block(event, data)
