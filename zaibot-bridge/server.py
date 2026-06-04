"""FastAPI 主入口: 接收 OpenAI 兼容请求，转发给 Z.ai。

API 端点:
- POST /v1/chat/completions  - OpenAI Chat Completions
- POST /v1/responses         - Codex Responses API
- POST /responses            - Codex Responses API (无 /v1 前缀)
- GET  /v1/models            - 模型列表
- POST /api/close            - 关闭会话
- GET  /api/status           - 服务状态
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# 将 bridge 目录加入 path
sys.path.insert(0, os.path.dirname(__file__))

from bridge.models import InternalRequest, InternalStreamEvent
from bridge.model_alias import resolve_model, list_models_for_api
from bridge.runtime import ChatRuntimeService
from bridge.adapters import chat as chat_adapter
from bridge.adapters import responses as responses_adapter

# 全局运行时服务
runtime: ChatRuntimeService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global runtime
    runtime = ChatRuntimeService()

    # 后台清理协程：每 60 秒 sweep 一次过期会话
    import asyncio
    _sweep_stop = asyncio.Event()

    async def _session_sweep_loop():
        while not _sweep_stop.is_set():
            try:
                await asyncio.wait_for(_sweep_stop.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                pass
            if runtime:
                evicted = runtime.sweep_expired_sessions()
                if evicted:
                    print(f"[session-cache] swept {evicted} expired sessions", file=sys.stderr)

    sweep_task = asyncio.create_task(_session_sweep_loop())
    yield
    _sweep_stop.set()
    sweep_task.cancel()
    try:
        await sweep_task
    except asyncio.CancelledError:
        pass
    runtime = None


app = FastAPI(
    title="Z.ai Bridge",
    description="OpenAI 兼容 API 代理，底层使用 Z.ai",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {"message": "Z.ai Bridge is running"}


@app.get("/v1/models")
async def list_models():
    """返回支持的模型列表（从 Z.ai API 动态获取）。"""
    return {
        "object": "list",
        "data": list_models_for_api(),
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI Chat Completions API。"""
    body = await request.json()

    # 解析请求
    req = chat_adapter.normalize_request(body)
    req = req.with_model(resolve_model(req.model))

    # 执行请求
    if req.stream:
        # 流式响应
        async def generate():
            async for sse in chat_adapter.to_sse_stream(runtime.execute(req), req.model):
                yield sse

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # 非流式响应
        text_parts = []
        async for event in runtime.execute(req):
            from bridge.models import TextDelta
            if isinstance(event, TextDelta):
                text_parts.append(event.chunk)

        response = chat_adapter.to_non_stream_response(
            "".join(text_parts), req.model
        )
        return JSONResponse(response)


@app.post("/v1/responses")
@app.post("/responses")
async def responses_api(request: Request):
    """Codex Responses API。"""
    body = await request.json()

    # 解析请求
    req = responses_adapter.normalize_request(body)
    req = req.with_model(resolve_model(req.model))

    # 生成 response_id
    response_id = f"resp_{uuid.uuid4().hex[:12]}"

    # 提取 session_id
    session_id = (
        request.headers.get("session-id")
        or request.headers.get("x-codex-session-id")
        or body.get("session_id")
        or body.get("conversation_id")
    )
    if session_id:
        req = req.with_conversation_id(session_id)

    # 流式响应
    async def generate():
        async for sse in responses_adapter.to_sse(
            runtime.execute(req), req, response_id
        ):
            yield sse

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat")
async def legacy_chat(request: Request):
    """旧协议兼容 (纯文本)。"""
    body = await request.json()
    prompt = body.get("message") or body.get("prompt") or ""
    model = body.get("model") or "GLM-5.1"
    session_id = body.get("session_id")

    req = InternalRequest(
        model=resolve_model(model),
        messages=[],
        stream=False,
        conversation_id=session_id,
    )
    # 添加用户消息
    from bridge.models import Message
    req = req.with_messages([Message("user", prompt)])

    # 执行请求
    text_parts = []
    async for event in runtime.execute(req):
        from bridge.models import TextDelta
        if isinstance(event, TextDelta):
            text_parts.append(event.chunk)

    return JSONResponse({
        "response": "".join(text_parts),
        "model": req.model,
    })


@app.post("/api/close")
async def close_session(request: Request):
    """关闭会话。"""
    body = await request.json()
    session_id = body.get("session_id")

    if session_id and runtime:
        runtime.close_session(session_id)
        return JSONResponse({"status": "ok", "session_id": session_id})

    return JSONResponse(
        {"status": "error", "message": "session_id required"},
        status_code=400,
    )


@app.get("/api/status")
async def status():
    """服务状态。"""
    if runtime:
        stats = runtime.session_stats()
        return {
            "status": "running",
            "sessions": stats.size,
            "session_max": stats.max_size,
            "session_ttl_seconds": stats.ttl_seconds,
            "evicted_ttl": stats.evicted_ttl,
            "evicted_lru": stats.evicted_lru,
            "timestamp": int(time.time()),
        }
    return {
        "status": "stopped",
        "timestamp": int(time.time()),
    }


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8001,  # 使用 8001 端口避免与 deepseek-bridge 冲突
        reload=False,
    )
