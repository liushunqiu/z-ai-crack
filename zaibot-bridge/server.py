"""FastAPI 主入口: 接收 OpenAI 兼容请求，转发给 Z.ai。

API 端点:
- POST /v1/chat/completions  - OpenAI Chat Completions
- POST /v1/responses         - Codex Responses API
- POST /responses            - Codex Responses API (无 /v1 前缀)
- GET  /v1/models            - 模型列表
- POST /api/close            - 关闭会话
- GET  /api/status           - 服务状态
- GET  /admin                - Web 管理界面 (HTML)
- GET  /admin/api/...        - 管理 API
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

# 将 bridge 目录和项目根目录加入 path
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 代理提示: 全局 SOCKS5 monkey-patch 已移除, 代理现在由 Account.proxy 字段按账号绑定,
# 在 runtime._pure_http_streaming() 里通过 socks_urllib.make_opener() 单次生效。
# ZAIBOT_PROXY 环境变量仍可作为账号 proxy 为空时的回退值。
_zaibot_proxy_fallback = os.environ.get("ZAIBOT_PROXY", "")
if _zaibot_proxy_fallback:
    print(f"[proxy] ZAIBOT_PROXY={_zaibot_proxy_fallback} (仅作为账号 proxy 为空时的回退)")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_logger = logging.getLogger(__name__)

from bridge.models import InternalRequest, InternalStreamEvent
from bridge.model_alias import resolve_model, list_models_for_api
from bridge.runtime import ChatRuntimeService
from bridge.db import AccountDB
from bridge.account_manager import AccountManager
from bridge.adapters import chat as chat_adapter
from bridge.adapters import responses as responses_adapter

# 全局运行时服务
runtime: ChatRuntimeService | None = None
account_manager: AccountManager | None = None

BRIDGE_DIR = Path(__file__).parent
STATIC_DIR = BRIDGE_DIR / "static"
DATA_DIR = BRIDGE_DIR / "data"

# Admin API 认证
_admin_key = os.environ.get("ZAIBOT_ADMIN_KEY", "")
_api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def verify_admin_key(request: Request, api_key: str | None = Security(_api_key_header)):
    """验证 Admin API 访问权限。

    优先级:
    1. 请求头携带 X-Admin-Key 且与 ZAIBOT_ADMIN_KEY 匹配 → 通过
    2. ZAIBOT_ADMIN_KEY 未设置 → 仅允许本机访问 (127.0.0.1 / ::1)
    3. 其他情况 → 403
    """
    global _admin_key
    if _admin_key:
        if api_key == _admin_key:
            return
        raise HTTPException(status_code=403, detail="Invalid admin key")
    # 未配置密钥时仅允许本机
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1", "localhost"):
        return
    raise HTTPException(
        status_code=403,
        detail="Admin API disabled for remote access. Set ZAIBOT_ADMIN_KEY to enable remote admin.",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global runtime, account_manager

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = AccountDB(DATA_DIR / "accounts.db")
    account_manager = AccountManager(db, data_dir=DATA_DIR)
    runtime = ChatRuntimeService(account_manager)

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
                    _logger.info("Session cache swept %d expired sessions", evicted)

    sweep_task = asyncio.create_task(_session_sweep_loop())
    yield
    _sweep_stop.set()
    sweep_task.cancel()
    try:
        await sweep_task
    except asyncio.CancelledError:
        pass
    if account_manager:
        account_manager.close_all()
    runtime = None
    account_manager = None


app = FastAPI(
    title="Z.ai Bridge",
    description="OpenAI 兼容 API 代理，底层使用 Z.ai",
    version="1.0.0",
    lifespan=lifespan,
)

_cors_origins = os.environ.get("ZAIBOT_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


# =====================================================================
# 管理界面 (/admin)
# =====================================================================

@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def admin_index():
    """管理界面首页。"""
    index = STATIC_DIR / "admin.html"
    if not index.exists():
        return JSONResponse(
            {"error": f"admin.html not found at {index}"},
            status_code=500,
        )
    return FileResponse(index, media_type="text/html")


@app.get("/admin/api/accounts", dependencies=[Depends(verify_admin_key)])
async def admin_list_accounts():
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    return {"accounts": account_manager.list_accounts()}


@app.post("/admin/api/accounts", dependencies=[Depends(verify_admin_key)])
async def admin_create_account(request: Request):
    """创建新账号 (status=pending_login, 等待 start_interactive_login)。"""
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name 不能为空")
    try:
        acc = account_manager.create_account(name)
        return {"account": acc}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/admin/api/accounts/{account_id}/login", dependencies=[Depends(verify_admin_key)])
async def admin_start_login(account_id: int, request: Request):
    """启动 headful 浏览器, 用户手动登录, 完成后保存 state 并标记 active。

    这是同步阻塞调用 (会等到登录完成或超时), 可能需要 30s-5min。
    """
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")

    # 进度回调, 通过 SSE 推送给前端
    accept = request.headers.get("accept", "")
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    use_sse = "text/event-stream" in accept

    if not use_sse:
        # 简单阻塞模式
        result = await _run_login_blocking(account_id, lambda msg: _logger.info("[admin-login] %s", msg))
        return {"ok": result}

    # SSE 进度模式
    async def event_stream():
        import asyncio as _aio
        loop = _aio.get_event_loop()
        q: _aio.Queue = _aio.Queue()

        def progress_q(msg: str):
            loop.call_soon_threadsafe(q.put_nowait, msg)

        def task():
            try:
                ok = account_manager.start_interactive_login(account_id, on_progress=progress_q)
                loop.call_soon_threadsafe(q.put_nowait, {"__done__": True, "ok": ok})
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, {"__error__": True, "message": str(e)})

        threading.Thread(target=task, daemon=True).start()

        while True:
            item = await q.get()
            if isinstance(item, dict) and item.get("__done__"):
                yield f"data: {json.dumps({'progress': 'done', 'ok': item['ok']}, ensure_ascii=False)}\n\n"
                break
            if isinstance(item, dict) and item.get("__error__"):
                yield f"data: {json.dumps({'progress': 'error', 'message': item['message']}, ensure_ascii=False)}\n\n"
                break
            yield f"data: {json.dumps({'progress': item}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _run_login_blocking(account_id: int, on_progress) -> bool:
    """在 threadpool 中跑同步登录流程, 避免阻塞事件循环。"""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: account_manager.start_interactive_login(account_id, on_progress=lambda m: _logger.info("[admin-login] %s", m)),
    )


@app.delete("/admin/api/accounts/{account_id}", dependencies=[Depends(verify_admin_key)])
async def admin_delete_account(account_id: int):
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    ok = account_manager.delete_account(account_id)
    if not ok:
        raise HTTPException(404, "账号不存在")
    return {"ok": True}


@app.post("/admin/api/accounts/{account_id}/test", dependencies=[Depends(verify_admin_key)])
async def admin_test_account(account_id: int):
    """端到端测试: state + captcha + API。通过则自动 mark active。

    阻塞调用, 通常 5-15 秒。
    """
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    import asyncio
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: account_manager.test_account(account_id)
    )
    if not result["ok"]:
        raise HTTPException(400, result.get("message", "test failed"))
    return result


@app.patch("/admin/api/accounts/{account_id}", dependencies=[Depends(verify_admin_key)])
async def admin_update_account(account_id: int, request: Request):
    """更新账号: status / note / proxy。"""
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    body = await request.json()
    try:
        if "proxy" in body:
            result = account_manager.set_proxy(account_id, body["proxy"] or "")
            if not result.get("ok"):
                raise HTTPException(400, result.get("message", "set_proxy failed"))
            return {"ok": True, "old": result["old"], "new": result["new"]}
        if "status" in body:
            return {"account": account_manager.set_status(account_id, body["status"])}
        if "note" in body:
            account_manager.db.update_account(account_id, note=body["note"])
            return {"ok": True, "note": body["note"]}
        raise HTTPException(400, "支持字段: status / note / proxy")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/admin/api/accounts/{account_id}/reset", dependencies=[Depends(verify_admin_key)])
async def admin_reset_account(account_id: int):
    """重置账号：清除状态文件，设置为 pending_login 状态。

    用于处理被风控的账号：
    1. 关闭浏览器会话
    2. 删除状态文件
    3. 将账号状态设置为 pending_login
    """
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    try:
        result = account_manager.reset_account(account_id)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"重置失败: {e}")


@app.get("/admin/api/accounts/{account_id}/cooldown", dependencies=[Depends(verify_admin_key)])
async def admin_get_account_cooldown(account_id: int):
    """获取账号的冷却期状态。"""
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    try:
        info = account_manager.get_account_cooldown_info(account_id)
        return info
    except Exception as e:
        raise HTTPException(500, f"获取冷却期状态失败: {e}")


@app.get("/admin/api/bindings", dependencies=[Depends(verify_admin_key)])
async def admin_list_bindings():
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    return {"bindings": account_manager.list_bindings()}


@app.get("/admin/api/bindings/{session_id}", dependencies=[Depends(verify_admin_key)])
async def admin_get_binding(session_id: str):
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    info = account_manager.get_binding_info(session_id)
    if not info:
        raise HTTPException(404, "未找到绑定")
    return info


@app.patch("/admin/api/bindings/{session_id}", dependencies=[Depends(verify_admin_key)])
async def admin_rebind_session(session_id: str, request: Request):
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    body = await request.json()
    account_id = body.get("account_id")
    if not isinstance(account_id, int):
        raise HTTPException(400, "account_id (int) 必填")
    try:
        return account_manager.rebind_session(session_id, account_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/admin/api/bindings/{session_id}", dependencies=[Depends(verify_admin_key)])
async def admin_unbind_session(session_id: str):
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    ok = account_manager.unbind_session(session_id)
    return {"ok": ok}


@app.get("/admin/api/events", dependencies=[Depends(verify_admin_key)])
async def admin_list_events(limit: int = 50):
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    return {"events": account_manager.db.list_events(limit=limit)}


@app.get("/admin/api/resolve", dependencies=[Depends(verify_admin_key)])
async def admin_resolve_session(session_id: str):
    """预览: 给定 session_id 会绑定到哪个账号 (不实际绑定)。"""
    if not account_manager:
        raise HTTPException(503, "AccountManager not initialized")
    info = account_manager.get_binding_info(session_id)
    if info:
        return {"bound": True, "info": info}
    active = account_manager.db.list_active_accounts()
    return {"bound": False, "active_count": len(active), "active_names": [a.name for a in active]}


if __name__ == "__main__":
    _host = os.environ.get("ZAIBOT_HOST", "127.0.0.1")
    uvicorn.run(
        "server:app",
        host=_host,
        port=8001,  # 使用 8001 端口避免与 deepseek-bridge 冲突
        reload=False,
    )
