"""ChatRuntimeService: 请求 -> Z.ai API -> 事件流。

负责：
1. 会话管理 (session_id -> ChatSession 映射)
2. 调用 zaibot_core 发送请求
3. 解析 Z.ai SSE 流
4. 产出 InternalStreamEvent 流
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from typing import AsyncIterator

from .models import (
    InternalRequest,
    InternalStreamEvent,
    TextDelta,
    ThinkingDelta,
    Finish,
    StreamError,
)
from .dsml import ToolCallStreamParser
from .prompt_compat import flatten_to_prompt

# 将 zaibot 目录加入 path 以便导入
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "zaibot"))

import zaibot_core
from captcha_service import CaptchaSession

# 全局 CaptchaSession 实例（持久浏览器，避免每次启动新浏览器）
_captcha_session: CaptchaSession | None = None


def _get_captcha_session() -> CaptchaSession:
    """获取或创建全局 CaptchaSession。"""
    global _captcha_session
    if _captcha_session is None:
        _captcha_session = CaptchaSession(headless=True)
        _captcha_session.start()
    return _captcha_session


def _get_fresh_captcha(max_retries: int = 2) -> str | None:
    """获取新的 captcha token（每次调用都获取新 token，因为 captcha 是一次性的）。"""
    for attempt in range(max_retries + 1):
        try:
            sess = _get_captcha_session()
            token = sess.get_captcha()
            return token
        except Exception as e:
            print(f"[!] 获取 captcha 失败 (attempt {attempt + 1}/{max_retries + 1}): {e}", file=sys.stderr)
            if attempt < max_retries:
                global _captcha_session
                try:
                    _captcha_session.close()
                except Exception:
                    pass
                _captcha_session = None
    return None


class ChatRuntimeService:
    """管理会话并执行请求。"""

    def __init__(self) -> None:
        self._sessions: dict[str, zaibot_core.ChatSession] = {}

    def _get_or_create_session(self, session_id: str | None, model: str) -> zaibot_core.ChatSession:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        session = zaibot_core.ChatSession(model=model)
        if session_id:
            self._sessions[session_id] = session
        return session

    async def execute(self, req: InternalRequest) -> AsyncIterator[InternalStreamEvent]:
        """执行请求并产出事件流。

        使用 asyncio.to_thread 将阻塞的 HTTP 请求放到线程池执行,
        请求完成后一次性 yield 所有事件。
        """
        session_id = req.conversation_id
        session = self._get_or_create_session(session_id, req.model)
        # 首次请求发送完整内容（系统提示+工具定义+历史），后续请求只发新消息
        is_first = session.chat_id is None
        prompt = self._flatten_messages(req, is_first=is_first)
        tool_parser = ToolCallStreamParser()

        def do_request_sync() -> list[InternalStreamEvent]:
            """同步执行 HTTP 请求,返回事件列表。"""
            import urllib.parse

            max_retries = 2
            last_error = None

            for attempt in range(max_retries + 1):
                events = []
                try:
                    print(f"[*] === 请求 attempt {attempt}/{max_retries} ===", file=sys.stderr)

                    token = zaibot_core.read_token()
                    user_id = zaibot_core.get_user_id(token)
                    if not user_id:
                        return [StreamError("无法从 JWT 解析 user_id")]

                    timestamp = zaibot_core.now_ms()
                    request_id = zaibot_core.new_id()
                    signature, signature_timestamp, _ = zaibot_core.get_signature(
                        prompt, timestamp, request_id, user_id
                    )

                    if session.chat_id:
                        chat_id = session.chat_id
                        print(f"[*] 复用已有 chat_id: {chat_id}", file=sys.stderr)
                    else:
                        chat_id = zaibot_core.create_chat(req.model)
                        session.chat_id = chat_id
                        print(f"[*] 创建新 chat_id: {chat_id}", file=sys.stderr)

                    parent_id = session.last_assistant_id

                    # 获取 captcha（每次请求都获取新 token，因为 captcha 是一次性的）
                    captcha_verify_param = _get_fresh_captcha()

                    body_dict, assistant_id = zaibot_core.build_body(
                        prompt, model=req.model, stream=True,
                        captcha_verify_param=captcha_verify_param,
                        chat_id=chat_id, parent_id=parent_id,
                    )

                    params = zaibot_core.build_query_params(
                        token, user_id, timestamp, request_id, signature_timestamp
                    )
                    headers = zaibot_core.build_headers(token, signature)

                    query_string = urllib.parse.urlencode(params)
                    path = f"/api/v2/chat/completions?{query_string}"
                    body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")

                    print(f"[*] 发送请求到 Z.ai (chat_id={chat_id})...", file=sys.stderr)

                    # 使用 http.client 代替 urllib.request（避免 WAF 405）
                    import http.client
                    conn = http.client.HTTPSConnection("chat.z.ai", timeout=180)
                    conn.request("POST", path, body=body, headers=headers)
                    resp = conn.getresponse()

                    content_type = (resp.getheader("content-type") or "").lower()
                    print(f"[*] 响应: status={resp.status}, content-type={content_type}", file=sys.stderr)

                    if resp.status >= 400:
                        err_body = resp.read().decode("utf-8", errors="replace")
                        print(f"[!] HTTP 错误: status={resp.status}, body={err_body[:500]}", file=sys.stderr)
                        conn.close()
                        raise zaibot_core.ZaibotHTTPError(resp.status, err_body, f"https://chat.z.ai{path}")

                    # 包装成类文件对象以兼容后续代码
                    class _HttpResponse:
                        def __init__(self, resp, conn):
                            self._resp = resp
                            self._conn = conn
                            self.headers = resp
                        def __iter__(self):
                            return self
                        def __next__(self):
                            line = self._resp.readline()
                            if not line:
                                raise StopIteration
                            return line
                        def read(self, size=-1):
                            return self._resp.read(size)
                        def close(self):
                            self._conn.close()
                        def __enter__(self):
                            return self
                        def __exit__(self, *args):
                            self.close()

                    resp = _HttpResponse(resp, conn)

                    if "text/event-stream" in content_type:
                        for raw_line in resp:
                            line = raw_line.decode("utf-8", errors="replace").strip()
                            if not line or line == "data: [DONE]":
                                continue
                            if not line.startswith("data: "):
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
                                    break  # 重试（保留 chat_id，下次获取新 captcha）
                                return [StreamError(err_str)]

                            payload = data.get("data", {}) if isinstance(data, dict) else {}
                            if isinstance(payload, str):
                                continue
                            if isinstance(payload, dict):
                                phase = payload.get("phase")
                                delta_content = payload.get("delta_content")
                                if phase == "thinking" and delta_content:
                                    events.append(ThinkingDelta(delta_content))
                                elif phase == "answer" and delta_content:
                                    for ev in tool_parser.feed(delta_content):
                                        events.append(ev)

                        # 如果 break 了（captcha 重试），events 为空，继续循环
                        if not events and attempt < max_retries:
                            print(f"[*] SSE 流结束但无事件 (attempt {attempt})，重试...", file=sys.stderr)
                            continue

                        # 流结束
                        for ev in tool_parser.flush():
                            events.append(ev)
                        session.last_assistant_id = assistant_id
                        return events

                    else:
                        raw = resp.read()
                        data = json.loads(raw)
                        err = zaibot_core._extract_error_payload(data)
                        if err:
                            err_str = json.dumps(err, ensure_ascii=False)
                            kind = zaibot_core.classify_error(200, err_str)
                            last_error = err_str
                            if zaibot_core.is_retriable_error(kind) and attempt < max_retries:
                                continue
                            return [StreamError(err_str)]

                        result = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if result:
                            events.append(TextDelta(result))
                        session.last_assistant_id = assistant_id
                        return events

                except zaibot_core.ZaibotHTTPError as e:
                    kind = zaibot_core.classify_error(e.status, e.body)
                    last_error = f"HTTP {e.status}: {e.body[:500]}"
                    print(f"[!] ZaibotHTTP 错误 (attempt {attempt}): {last_error[:200]}", file=sys.stderr)
                    if zaibot_core.is_retriable_error(kind) and attempt < max_retries:
                        print(f"[*] 可重试 HTTP 错误，重试...", file=sys.stderr)
                        continue
                    return [StreamError(last_error, e.status)]
                except zaibot_core.ZaibotAPIError as e:
                    last_error = f"{e.kind}: {e.body[:500]}"
                    print(f"[!] API 错误 (attempt {attempt}): {last_error[:200]}", file=sys.stderr)
                    if zaibot_core.is_retriable_error(e.kind) and attempt < max_retries:
                        print(f"[*] 可重试 API 错误，重试...", file=sys.stderr)
                        continue
                    return [StreamError(last_error)]
                except zaibot_core.ZaibotError as e:
                    print(f"[!] Zaibot 错误 (attempt {attempt}): {e}", file=sys.stderr)
                    return [StreamError(str(e))]
                except Exception as e:
                    print(f"[!] 未知错误 (attempt {attempt}): {type(e).__name__}: {e}", file=sys.stderr)
                    return [StreamError(f"未知错误: {str(e)}")]

            return [StreamError(f"请求失败，已重试 {max_retries} 次: {last_error}")]

        # 在线程池中执行阻塞的 HTTP 请求
        events = await asyncio.to_thread(do_request_sync)

        # 逐个 yield 事件
        for event in events:
            yield event

    def _flatten_messages(self, req: InternalRequest, *, is_first: bool = True) -> str:
        """拍平消息。首次请求发送系统提示+工具定义+历史，后续请求只发新增消息（含工具结果）。"""
        return flatten_to_prompt(req, first_turn=is_first)

    def close_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
