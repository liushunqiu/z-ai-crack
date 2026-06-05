"""ChatRuntimeService: 请求 -> Z.ai API -> 事件流。

负责：
1. 会话管理 (session_id -> ChatSession 映射, per-account)
2. 通过 AccountManager 解析 session_id 对应的 Z.ai 账号
3. 调用 zaibot_core 发送请求 (使用该账号的 token + cookie)
4. 解析 Z.ai SSE 流
5. 产出 InternalStreamEvent 流

环境变量:
- ZAIBOT_USE_PURE_HTTP=1: chat-completion 走 urllib 路径 (跳过 Camoufox fetch)
  Captcha/fingerprint 仍从 Camoufox 拿, 适用于 DOM-fetch 持续 F018 但 pure HTTP 正常的场景
"""
from __future__ import annotations
import asyncio
import json
import os
import queue
import sys
import urllib.error
import urllib.request
import threading
import time
import urllib.parse
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
    # 每个账号的最小请求间隔（秒）
    MIN_REQUEST_INTERVAL = 2.0
    # 切到 pure HTTP 路径: env ZAIBOT_USE_PURE_HTTP=1
    USE_PURE_HTTP = os.environ.get("ZAIBOT_USE_PURE_HTTP", "").lower() in ("1", "true", "yes")

    def __init__(self, account_manager) -> None:
        self.account_manager = account_manager
        self._sessions: TTLCache[zaibot_core.ChatSession] = TTLCache(
            max_size=self.SESSION_MAX_SIZE,
            ttl_seconds=self.SESSION_TTL_SECONDS,
        )
        # 每个账号的最后请求时间
        self._last_request_time: dict[int, float] = {}
        self._request_interval_lock = threading.Lock()

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

        # ====== IP 级别风控: 全局冷却检查 ======
        ip_remaining = self.account_manager.check_ip_cooldown()
        if ip_remaining is not None:
            mins = ip_remaining / 60
            yield StreamError(
                f"IP 级别风控冷却中, 剩余 {mins:.1f} 分钟。"
                f"多账号同窗口被阿里云 WAF 限流, 已自动暂停所有账号。"
            )
            return

        # ====== IP 级别风控: 全局最小间隔 (跨账号) ======
        # 同步阻塞等槽位 — 在 threadpool 里跑, 不阻塞事件循环
        loop = asyncio.get_event_loop()
        def _wait_ip_slot():
            return self.account_manager.acquire_ip_slot()
        ip_wait = await loop.run_in_executor(None, _wait_ip_slot)
        if ip_wait > 0:
            print(f"[*] IP 槽位等待 {ip_wait:.2f}s", file=sys.stderr)

        # 单账号最小间隔 (保留原行为)
        account_id = account.id
        with self._request_interval_lock:
            last_time = self._last_request_time.get(account_id, 0)
            elapsed = time.time() - last_time
            if elapsed < self.MIN_REQUEST_INTERVAL:
                wait_time = self.MIN_REQUEST_INTERVAL - elapsed
                print(f"[*] 请求间隔等待 {wait_time:.1f}s (account={account.name})", file=sys.stderr)
                await asyncio.sleep(wait_time)
            self._last_request_time[account_id] = time.time()

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
            last_error_kind: Optional[str] = None
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
                    captcha_verify_param, fingerprint = self._get_fresh_captcha_for_account(account_id)

                    if not captcha_verify_param:
                        msg = "captcha 生成失败 (send button 持续 disabled 或无 cert), 跳过本 attempt"
                        print(f"[!] {msg}", file=sys.stderr)
                        event_queue.put(StreamError(msg))
                        event_queue.put(None)
                        return

                    last_user_text = next(
                        (m.content for m in reversed(req.messages)
                         if m.role == "user" and m.content),
                        None,
                    )
                    variables = {
                        "{{USER_LANGUAGE}}": zaibot_core.detect_user_language(last_user_text or ""),
                    }

                    body_dict, assistant_id = zaibot_core.build_body(
                        prompt, model=req.model, stream=True,
                        captcha_verify_param=captcha_verify_param,
                        chat_id=chat_id, parent_id=parent_id,
                        variables=variables,
                    )

                    params = zaibot_core.build_query_params(
                        token, user_id, timestamp, request_id, signature_timestamp,
                        fingerprint=fingerprint,
                    )
                    cookie = zaibot_core.load_cookie_header_from_state(state_path)
                    headers = zaibot_core.build_headers_with_cookie(
                        token, signature, cookie, fingerprint=fingerprint,
                    )

                    query_string = urllib.parse.urlencode(params)
                    path = f"/api/v2/chat/completions?{query_string}"
                    body_str = json.dumps(body_dict, ensure_ascii=False)

                    print(f"[*] 发送流式请求到 Z.ai via Camoufox (account={account.name}, chat_id={chat_id})...", file=sys.stderr)

                    # In-browser fetch via the captcha session's persistent page.
                    # Going through Camoufox means the chat-completion request
                    # shares the exact same TLS/HTTP/canvas fingerprint as the
                    # captcha that was just generated — no verify_failed
                    # mismatch.
                    captcha_sess = self.account_manager.get_captcha_session(account_id)
                    if captcha_sess is None:
                        raise zaibot_core.ZaibotError("没有 captcha session 可用")

                    sse_event_count = 0
                    retriable_sse_error = False
                    resp_status = None
                    error_body_buf: list[str] = []
                    saw_error_status = False

                    # 选路径: pure HTTP (urllib) vs DOM fetch (Camoufox)
                    if self.USE_PURE_HTTP:
                        print(f"[*] 路径: PURE HTTP (urllib, 跳过 Camoufox fetch)", file=sys.stderr)
                        item_iter = self._pure_http_streaming(path, headers, body_str)
                    else:
                        print(f"[*] 路径: DOM FETCH (Camoufox 持久 page)", file=sys.stderr)
                        item_iter = captcha_sess.fetch_streaming(path, headers, body_str)

                    for item in item_iter:
                        if "status" in item:
                            resp_status = int(item["status"])
                            if resp_status >= 400:
                                saw_error_status = True
                                print(f"[!] HTTP 错误: status={resp_status}", file=sys.stderr)
                            continue
                        if "chunk" not in item:
                            continue
                        chunk_text = item["chunk"]
                        if saw_error_status:
                            error_body_buf.append(chunk_text)
                            continue
                        for raw_line in chunk_text.split("\n"):
                            line = raw_line.strip()
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
                                last_error_kind = kind
                                print(f"[!] SSE 错误 (attempt {attempt}): kind={kind}, err={err_str[:200]}", file=sys.stderr)
                                # IP 级别上报 (限流/verify_failed 会触发集群检测, 必须传 body)
                                self.account_manager.report_request_failure(kind, err_str, account_id)
                                if zaibot_core.is_retriable_error(kind) and attempt < max_retries:
                                    if is_first and session.chat_id is not None and session.last_assistant_id is None:
                                        session.chat_id = None
                                        print(f"[*] 首次消息失败且无 assistant 回复，重置 chat_id 避免服务端状态污染", file=sys.stderr)
                                    # verify_failed / FRONTEND_CAPTCHA_REQUIRED 视为 IP 限流信号:
                                    # 重试等于送死, 直接退避
                                    if "verify_failed" in err_str or "FRONTEND_CAPTCHA_REQUIRED" in err_str:
                                        backoff = 5 * (2 ** attempt)
                                        print(f"[!] verify_failed → 退避 {backoff}s 后再重试 (避免雪上加霜)", file=sys.stderr)
                                        time.sleep(backoff)
                                    print(f"[*] 可重试错误，{'保留' if session.chat_id else '重置后'}chat_id 并重试...", file=sys.stderr)
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
                            break

                    if saw_error_status:
                        body = "".join(error_body_buf)
                        raise zaibot_core.ZaibotHTTPError(resp_status or 0, body, path)

                    if retriable_sse_error:
                        continue

                    if not sse_event_count and attempt < max_retries:
                        print(f"[*] SSE 流结束但无事件 (attempt {attempt})，重试...", file=sys.stderr)
                        continue

                    for ev in tool_parser.flush():
                        event_queue.put(ev)
                    session.last_assistant_id = assistant_id
                    request_succeeded = True
                    # IP 级别上报: 成功清空集群失败窗口
                    self.account_manager.report_request_success()
                    event_queue.put(None)
                    return

                except zaibot_core.ZaibotHTTPError as e:
                    kind = zaibot_core.classify_error(e.status, e.body)
                    last_error = f"HTTP {e.status}: {e.body[:500]}"
                    last_error_kind = kind
                    print(f"[!] ZaibotHTTP 错误 (attempt {attempt}): {last_error[:200]}", file=sys.stderr)
                    # IP 级别上报 (传 body 才能识别 verify_failed)
                    self.account_manager.report_request_failure(kind, e.body or "", account_id)
                    if zaibot_core.is_retriable_error(kind) and attempt < max_retries:
                        if kind == "限流" or "verify_failed" in (e.body or "") or "FRONTEND_CAPTCHA_REQUIRED" in (e.body or ""):
                            # Aliyun WAF blocked us - 风控限流 (IP 级别)
                            print(f"[!] 风控限流信号！账号 {account.name} + IP 全局 进入冷却期 (30分钟)", file=sys.stderr)
                            # 标记账号进入冷却期
                            self.account_manager.mark_rate_limited(account_id)
                            # 触发 IP 级别冷却, 暂停所有账号
                            self.account_manager.trigger_ip_cooldown(30, f"账号 {account.name} 触发 WAF")
                            # 不重试，直接返回错误
                            event_queue.put(StreamError(f"账号被风控，已自动暂停 30 分钟: {last_error}", e.status))
                            event_queue.put(None)
                            return
                        else:
                            # 退避重试 (避免雪崩)
                            backoff = 2 * (2 ** attempt)
                            print(f"[*] 可重试 HTTP 错误，退避 {backoff}s 后重试...", file=sys.stderr)
                            time.sleep(backoff)
                        continue
                    event_queue.put(StreamError(last_error, e.status))
                    event_queue.put(None)
                    return
                except zaibot_core.ZaibotAPIError as e:
                    last_error = f"{e.kind}: {e.body[:500]}"
                    last_error_kind = e.kind
                    print(f"[!] API 错误 (attempt {attempt}): {last_error[:200]}", file=sys.stderr)
                    # IP 级别上报 (传 body 才能识别 verify_failed)
                    self.account_manager.report_request_failure(e.kind, e.body or "", account_id)
                    if zaibot_core.is_retriable_error(e.kind) and attempt < max_retries:
                        if "verify_failed" in (e.body or "") or "FRONTEND_CAPTCHA_REQUIRED" in (e.body or ""):
                            backoff = 5 * (2 ** attempt)
                            print(f"[*] 可重试 API 错误 (verify_failed)，退避 {backoff}s 后重试...", file=sys.stderr)
                            time.sleep(backoff)
                        else:
                            print(f"[*] 可重试 API 错误，重试...", file=sys.stderr)
                        continue
                    event_queue.put(StreamError(last_error))
                    event_queue.put(None)
                    return
                except zaibot_core.ZaibotError as e:
                    last_error = str(e)
                    last_error_kind = "未知错误"
                    print(f"[!] Zaibot 错误 (attempt {attempt}): {e}", file=sys.stderr)
                    event_queue.put(StreamError(str(e)))
                    event_queue.put(None)
                    return
                except Exception as e:
                    last_error = f"未知错误: {str(e)}"
                    last_error_kind = "未知错误"
                    print(f"[!] 未知错误 (attempt {attempt}): {type(e).__name__}: {e}", file=sys.stderr)
                    event_queue.put(StreamError(f"未知错误: {str(e)}"))
                    event_queue.put(None)
                    return

            event_queue.put(StreamError(f"请求失败，已重试 {max_retries} 次: {last_error}"))
            event_queue.put(None)

            # 标记请求结果
            self.account_manager.mark_request(
                account_id,
                success=request_succeeded,
                kind=last_error_kind,
            )

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

    def _get_fresh_captcha_for_account(self, account_id: int, max_retries: int = 2) -> tuple[str | None, dict]:
        """获取指定账号的 captcha token + 浏览器 fingerprint。

        fingerprint 是从 Camoufox 浏览器里直接读出来的真实指纹，运行时再把
        chat-completions 请求也交给同一个 Camoufox fetch 完成（见 execute()），
        这样 captcha 的 `data` 字段和请求的浏览器上下文是 100% 一致的，
        Aliyun 不会因为 TLS/canvas 指纹不一致而 verify_failed。

        4G 多账号场景: 通过 account_manager.acquire_captcha_slot 限制全局
        并发 captcha 数, 防止 WAF 判定为"刷 captcha"。

        Returns (token, fingerprint_dict). fingerprint may be empty dict
        if the browser couldn't be fingerprinted (falls back to defaults).
        """
        for attempt in range(max_retries + 1):
            try:
                # 全局 captcha 并发限流 (4G 场景)
                self.account_manager.acquire_captcha_slot()
                try:
                    sess = self.account_manager.get_captcha_session(account_id)
                    token, fingerprint = sess.get_captcha()
                finally:
                    self.account_manager.release_captcha_slot()
                return token, (fingerprint or {})
            except Exception as e:
                print(f"[!] 获取 captcha 失败 (account_id={account_id}, attempt {attempt + 1}/{max_retries + 1}): {e}", file=sys.stderr)
        return None, {}

    def close_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def sweep_expired_sessions(self) -> int:
        """清除所有过期会话，返回清除数量。"""
        return self._sessions.sweep_expired()

    def session_stats(self):
        """返回会话缓存统计。"""
        return self._sessions.stats()

    def _pure_http_streaming(self, path: str, headers: dict, body: str):
        """Pure-HTTP 路径: 用 urllib 流式请求 chat-completion, 绕过 Camoufox fetch。

        和 captcha_sess.fetch_streaming 产出同样的 {status, chunk} 字典格式,
        让下游 SSE 解析代码完全无感切换。

        适用: DOM-fetch 持续 F018 / verify_failed 但 pure HTTP 正常的场景。
        代价: TLS fingerprint 跟 captcha page 不严格一致, captcha 可能 verify_failed。
        """
        url = f"https://chat.z.ai{path}" if path.startswith("/") else path
        req = urllib.request.Request(
            url, data=body.encode("utf-8"), headers=headers, method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as e:
            yield {"status": e.code, "type": "status"}
            try:
                yield {"chunk": e.read().decode("utf-8", "replace") + "\n\n"}
            except Exception:
                pass
            return

        yield {"status": resp.status, "type": "status"}
        if resp.status >= 400:
            try:
                yield {"chunk": resp.read().decode("utf-8", "replace") + "\n\n"}
            except Exception:
                pass
            return

        try:
            for raw in resp:
                if not raw:
                    continue
                chunk = raw.decode("utf-8", "replace")
                yield {"chunk": chunk}
        except Exception:
            pass

