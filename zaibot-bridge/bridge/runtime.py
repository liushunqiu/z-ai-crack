"""ChatRuntimeService: 请求 -> Z.ai API -> 事件流。

负责：
1. 会话管理 (session_id -> ChatSession 映射, per-account)
2. 通过 AccountManager 解析 session_id 对应的 Z.ai 账号
3. 调用 zaibot_core 发送请求 (使用该账号的 token + cookie)
4. 解析 Z.ai SSE 流
5. 产出 InternalStreamEvent 流
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from .models import (
    InternalRequest,
    InternalStreamEvent,
    TextDelta,
    ThinkingDelta,
    Finish,
    StreamError,
)
from .dsml import ToolCallStreamParser
from .session_cache import TTLCache
from .prompt_compat import flatten_to_prompt

# 将 zaibot 目录加入 path 以便导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "zaibot"))

import zaibot_core
from captcha_service import CaptchaSession


class ChatRuntimeService:
    """管理会话并执行请求。

    - ChatSession 池: session_id -> ChatSession (per-conversation chat state)
    - 通过 AccountManager 解析 session_id -> account_id (粘性绑定)
    - 每个账号独立的 CaptchaSession 浏览器 (用于 captcha token)
    - 实际的 chat API 请求通过 urllib + per-account token/cookie
    """

    SESSION_MAX_SIZE = 256
    SESSION_TTL_SECONDS = 1800.0

    def __init__(self, account_manager) -> None:
        self.account_manager = account_manager
        self._sessions: TTLCache[zaibot_core.ChatSession] = TTLCache(
            max_size=self.SESSION_MAX_SIZE,
            ttl_seconds=self.SESSION_TTL_SECONDS,
        )

    def _get_or_create_session(self, session_id: str | None, model: str) -> zaibot_core.ChatSession:
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            session.model = model
            return session
        session = zaibot_core.ChatSession(model=model)
        if session_id:
            self._sessions[session_id] = session
        return session

    async def execute(self, req: InternalRequest) -> AsyncIterator[InternalStreamEvent]:
        """执行请求并产出事件流。

        1. 通过 account_manager 解析 session_id 对应账号
        2. 拿该账号的 CaptchaSession 获取 captcha token
        3. 用该账号的 token + cookie 走 urllib 流式请求
        4. 通过 Queue 桥接线程池和 async generator
        """
        session_id = req.conversation_id
        session = self._get_or_create_session(session_id, req.model)
        is_first = session.chat_id is None
        prompt = self._flatten_messages(req, is_first=is_first)

        # 解析账号 (round-robin 绑定, sticky)
        account = self.account_manager.resolve_account(session_id)
        if account is None:
            yield StreamError("没有可用的 Z.ai 账号,请先在 /admin 添加并登录")
            return
        account_id = account.id
        state_path = Path(account.storage_path)

        event_queue: queue.Queue[InternalStreamEvent | None] = queue.Queue()

        def do_request_sync():
            """同步执行流式请求，将事件逐个放入队列。"""
            max_retries = 2
            last_error = None
            request_succeeded = False

            for attempt in range(max_retries + 1):
                tool_parser = ToolCallStreamParser()
                try:
                    print(f"[*] === 请求 attempt {attempt}/{max_retries} (account={account.name}) ===", file=sys.stderr)

                    token = zaibot_core.read_token_from_state(state_path)
                    user_id = zaibot_core.get_user_id(token)
                    if not user_id:
                        event_queue.put(StreamError("无法从 JWT 解析 user_id"))
                        event_queue.put(None)
                        return

                    timestamp = zaibot_core.now_ms()
                    request_id = zaibot_core.new_id()
                    signature, signature_timestamp, _ = zaibot_core.get_signature(
                        prompt, timestamp, request_id, user_id
                    )

                    if session.chat_id:
                        chat_id = session.chat_id
                        print(f"[*] 复用已有 chat_id: {chat_id}", file=sys.stderr)
                    else:
                        cookie_for_create = zaibot_core.load_cookie_header_from_state(state_path)
                        chat_id = zaibot_core.create_chat_with_token(token, cookie_for_create, req.model)
                        session.chat_id = chat_id
                        print(f"[*] 创建新 chat_id: {chat_id}", file=sys.stderr)

                    parent_id = session.last_assistant_id
                    captcha_verify_param = self._get_fresh_captcha_for_account(account_id)

                    body_dict, assistant_id = zaibot_core.build_body(
                        prompt, model=req.model, stream=True,
                        captcha_verify_param=captcha_verify_param,
                        chat_id=chat_id, parent_id=parent_id,
                    )

                    params = zaibot_core.build_query_params(
                        token, user_id, timestamp, request_id, signature_timestamp
                    )
                    cookie = zaibot_core.load_cookie_header_from_state(state_path)
                    headers = zaibot_core.build_headers_with_cookie(token, signature, cookie)

                    query_string = urllib.parse.urlencode(params)
                    path = f"/api/v2/chat/completions?{query_string}"
                    body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")

                    print(f"[*] 发送流式请求到 Z.ai (account={account.name}, chat_id={chat_id})...", file=sys.stderr)

                    full_url = f"https://chat.z.ai{path}"
                    http_req = urllib.request.Request(
                        full_url, data=body, headers=headers, method="POST"
                    )

                    sse_event_count = 0
                    retriable_sse_error = False

                    try:
                        resp = urllib.request.urlopen(http_req, timeout=180)
                    except urllib.error.HTTPError as e:
                        err_body = e.read().decode("utf-8", errors="replace")
                        raise zaibot_core.ZaibotHTTPError(e.code, err_body, full_url) from None

                    resp_status = resp.status
                    if resp_status >= 400:
                        print(f"[!] HTTP 错误: status={resp_status}", file=sys.stderr)
                        raise zaibot_core.ZaibotHTTPError(resp_status, "", full_url)

                    for raw_line in resp:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line or line == "data: [DONE]" or not line.startswith("data: "):
                            continue
                        try:
                            data = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue

                        err = zaibot_core._extract_error_payload(data)
                        if err:
                            err_str = json.dumps(err, ensure_ascii=False)
                            kind = zaibot_core.classify_error(200, err_str)
                            last_error = err_str
                            print(f"[!] SSE 错误 (attempt {attempt}): kind={kind}, err={err_str[:200]}", file=sys.stderr)
                            if zaibot_core.is_retriable_error(kind) and attempt < max_retries:
                                print(f"[*] 可重试错误，保留 chat_id 并重试...", file=sys.stderr)
                                retriable_sse_error = True
                                break
                            event_queue.put(StreamError(err_str))
                            event_queue.put(None)
                            return

                        payload = data.get("data", {}) if isinstance(data, dict) else {}
                        if isinstance(payload, str):
                            continue
                        if isinstance(payload, dict):
                            phase = payload.get("phase")
                            delta_content = payload.get("delta_content")
                            if phase == "thinking" and delta_content:
                                event_queue.put(ThinkingDelta(delta_content))
                                sse_event_count += 1
                            elif phase == "answer" and delta_content:
                                for ev in tool_parser.feed(delta_content):
                                    event_queue.put(ev)
                                    sse_event_count += 1

                    if retriable_sse_error:
                        continue

                    if not sse_event_count and attempt < max_retries:
                        print(f"[*] SSE 流结束但无事件 (attempt {attempt})，重试...", file=sys.stderr)
                        continue

                    for ev in tool_parser.flush():
                        event_queue.put(ev)
                    session.last_assistant_id = assistant_id
                    request_succeeded = True
                    event_queue.put(None)
                    return

                except zaibot_core.ZaibotHTTPError as e:
                    kind = zaibot_core.classify_error(e.status, e.body)
                    last_error = f"HTTP {e.status}: {e.body[:500]}"
                    print(f"[!] ZaibotHTTP 错误 (attempt {attempt}): {last_error[:200]}", file=sys.stderr)
                    if zaibot_core.is_retriable_error(kind) and attempt < max_retries:
                        print(f"[*] 可重试 HTTP 错误，重试...", file=sys.stderr)
                        continue
                    event_queue.put(StreamError(last_error, e.status))
                    event_queue.put(None)
                    return
                except zaibot_core.ZaibotAPIError as e:
                    last_error = f"{e.kind}: {e.body[:500]}"
                    print(f"[!] API 错误 (attempt {attempt}): {last_error[:200]}", file=sys.stderr)
                    if zaibot_core.is_retriable_error(e.kind) and attempt < max_retries:
                        print(f"[*] 可重试 API 错误，重试...", file=sys.stderr)
                        continue
                    event_queue.put(StreamError(last_error))
                    event_queue.put(None)
                    return
                except zaibot_core.ZaibotError as e:
                    print(f"[!] Zaibot 错误 (attempt {attempt}): {e}", file=sys.stderr)
                    event_queue.put(StreamError(str(e)))
                    event_queue.put(None)
                    return
                except Exception as e:
                    print(f"[!] 未知错误 (attempt {attempt}): {type(e).__name__}: {e}", file=sys.stderr)
                    event_queue.put(StreamError(f"未知错误: {str(e)}"))
                    event_queue.put(None)
                    return

            event_queue.put(StreamError(f"请求失败，已重试 {max_retries} 次: {last_error}"))
            event_queue.put(None)

            # 标记请求结果
            self.account_manager.mark_request(account_id, success=request_succeeded)

        # 在线程池中执行（不阻塞事件循环）
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, do_request_sync)

        # 从队列逐个读取事件并 yield（真流式：事件到达即转发）
        while True:
            item = await loop.run_in_executor(None, event_queue.get)
            if item is None:
                break
            yield item

    def _flatten_messages(self, req: InternalRequest, *, is_first: bool = True) -> str:
        """拍平消息。首次请求发送系统提示+工具定义+历史，后续请求只发新增消息（含工具结果）。"""
        return flatten_to_prompt(req, first_turn=is_first)

    def _get_fresh_captcha_for_account(self, account_id: int, max_retries: int = 2) -> str | None:
        """获取指定账号的 captcha token (每次调用都获取新 token, 因为 captcha 是一次性的)。"""
        for attempt in range(max_retries + 1):
            try:
                sess = self.account_manager.get_captcha_session(account_id)
                token = sess.get_captcha()
                return token
            except Exception as e:
                print(f"[!] 获取 captcha 失败 (account_id={account_id}, attempt {attempt + 1}/{max_retries + 1}): {e}", file=sys.stderr)
        return None

    def close_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def sweep_expired_sessions(self) -> int:
        """清除所有过期会话，返回清除数量。"""
        return self._sessions.sweep_expired()

    def session_stats(self):
        """返回会话缓存统计。"""
        return self._sessions.stats()

