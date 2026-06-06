#!/usr/bin/env python3
"""Shared pure-HTTP helpers for chat.z.ai.

This module intentionally uses only Python stdlib so the API client can run
without Playwright/Camoufox once login/signature/captcha material is available.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

BASE_DIR = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "zaibot_token.txt"
STATE_FILE = BASE_DIR / "zaibot_state.json"
CAPTURED_REQUEST_FILE = BASE_DIR / "captured_request.json"
SIGNATURE_CACHE_FILE = BASE_DIR / "zaibot_signature_cache.json"
CAPTCHA_CACHE_FILE = BASE_DIR / "zaibot_captcha_cache.json"

API_BASE = "https://chat.z.ai/api"
DEFAULT_MODEL = "GLM-5.1"
DEFAULT_TIMEZONE = "Asia/Shanghai"

FE_VERSION_CACHE_FILE = BASE_DIR / "zaibot_fe_version.json"
_FE_VERSION_CACHE: Optional[str] = None


def detect_fe_version(*, timeout: int = 10, max_age_hours: float = 24) -> str:
    """Auto-detect frontend version from chat.z.ai HTML.

    The version appears in <script src=".../prod-fe-X.Y.Z/assets/..."> tags.
    Uses file cache (24h TTL) to avoid fetching on every run.
    Falls back to a hardcoded default if detection fails.
    """
    import re

    global _FE_VERSION_CACHE
    if _FE_VERSION_CACHE:
        return _FE_VERSION_CACHE

    fallback = "prod-fe-1.1.38"

    # Check file cache first
    if FE_VERSION_CACHE_FILE.exists():
        try:
            data = json.loads(FE_VERSION_CACHE_FILE.read_text())
            cached = data.get("version", "")
            ts = float(data.get("timestamp", 0))
            if cached and time.time() - ts < max_age_hours * 3600:
                _FE_VERSION_CACHE = cached
                return cached
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    # Fetch from live page
    try:
        req = urllib.request.Request("https://chat.z.ai/")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read(16384).decode("utf-8", errors="replace")
        match = re.search(r'prod-fe-[\d.]+', html)
        if match:
            version = match.group(0)
            _FE_VERSION_CACHE = version
            try:
                FE_VERSION_CACHE_FILE.write_text(
                    json.dumps({"version": version, "timestamp": time.time()}),
                    encoding="utf-8",
                )
            except (OSError, PermissionError):
                pass
            return version
    except (urllib.error.URLError, TimeoutError, OSError):
        pass

    _FE_VERSION_CACHE = fallback
    return fallback


def get_fe_version() -> str:
    """Get FE_VERSION, using cached value or detecting on first call."""
    return detect_fe_version()


# Detect on import (non-blocking, falls back to hardcoded)
FE_VERSION = detect_fe_version()


class ChatSession:
    """Maintains conversation state across multiple post_chat calls.

    Usage:
        session = ChatSession(model="GLM-5.1")
        post_chat("你好", session=session)       # creates chat
        post_chat("第二条", session=session)      # same chat, chained
        post_chat("第三条", session=session)      # same chat, chained
    """

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self.chat_id: Optional[str] = None
        self.last_assistant_id: Optional[str] = None

    def reset(self):
        """Start a fresh conversation."""
        self.chat_id = None
        self.last_assistant_id = None


class ZaibotError(RuntimeError):
    pass


class ZaibotAPIError(ZaibotError):
    def __init__(self, kind: str, body: str):
        self.kind = kind
        self.body = body
        super().__init__(f"{kind}: {body[:500]}")


class ZaibotHTTPError(ZaibotError):
    def __init__(self, status: int, body: str, url: str):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status}: {classify_error(status, body)}: {body[:500]}")


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * ((4 - len(data) % 4) % 4))


def _read_state_local_storage(name: str) -> str:
    if not STATE_FILE.exists():
        return ""
    try:
        state = json.loads(STATE_FILE.read_text())
        for origin in state.get("origins", []):
            if origin.get("origin") == "https://chat.z.ai":
                for item in origin.get("localStorage", []):
                    if item.get("name") == name:
                        return item.get("value") or ""
    except (json.JSONDecodeError, OSError):
        return ""
    return ""


def _read_state_local_storage_from(name: str, state_path: Path) -> str:
    """Variant of _read_state_local_storage that reads from an explicit state file."""
    if not state_path.exists():
        return ""
    try:
        state = json.loads(state_path.read_text())
        for origin in state.get("origins", []):
            if origin.get("origin") == "https://chat.z.ai":
                for item in origin.get("localStorage", []):
                    if item.get("name") == name:
                        return item.get("value") or ""
    except (json.JSONDecodeError, OSError):
        return ""
    return ""


def read_token() -> str:
    # Prefer storage_state token: it is the browser truth and captcha/session
    # binding follows this token. Keep zaibot_token.txt synchronized.
    state_token = _read_state_local_storage("token").strip()
    if state_token:
        try:
            TOKEN_FILE.write_text(state_token, encoding="utf-8")
        except (OSError, PermissionError):
            pass
        return state_token
    if not TOKEN_FILE.exists():
        raise ZaibotError("未找到 zaibot_token.txt，请先运行: python3 login.py login")
    token = TOKEN_FILE.read_text().strip()
    if not token:
        raise ZaibotError("zaibot_token.txt 为空，请重新登录")
    return token


def get_user_id(token: str) -> str:
    try:
        parts = token.split(".")
        return json.loads(_b64url_decode(parts[1])).get("id", "")
    except (IndexError, KeyError, json.JSONDecodeError, ValueError):
        return ""


def get_user_name(default: str = "") -> str:
    try:
        raw = _read_state_local_storage("user") or _read_state_local_storage("USER")
        if raw:
            user = json.loads(raw)
            return user.get("name") or default
    except (json.JSONDecodeError, KeyError):
        return default
    return default


def read_token_from_state(state_path: Path) -> str:
    """Read JWT token from a specific state file (per-account support)."""
    state_token = _read_state_local_storage_from("token", state_path).strip()
    if state_token:
        return state_token
    if not state_path.exists():
        raise ZaibotError(f"State file not found: {state_path}")
    raise ZaibotError(f"No token in state file: {state_path}")


def get_user_name_from_state(state_path: Path, default: str = "") -> str:
    """Read display name from a specific state file (per-account support)."""
    try:
        raw = _read_state_local_storage_from("user", state_path) or _read_state_local_storage_from("USER", state_path)
        if raw:
            user = json.loads(raw)
            return user.get("name") or default
    except Exception:
        return default
    return default


def get_user_id_from_state(state_path: Path) -> str:
    """Convenience: read token from state and decode user_id."""
    return get_user_id(read_token_from_state(state_path))


def now_ms() -> str:
    return str(int(time.time() * 1000))


def new_id() -> str:
    return str(uuid.uuid4())


def sorted_payload(timestamp: str, request_id: str, user_id: str) -> str:
    """Frontend rV() sortedPayload format.

    Object.entries(o).sort((a,b)=>a[0].localeCompare(b[0])).join(',') on
    entries like ["requestId", value] stringifies each pair as "key,value".
    """
    payload = {"requestId": request_id, "timestamp": timestamp, "user_id": user_id}
    return ",".join(f"{k},{payload[k]}" for k in sorted(payload))


def sign_with_secret(secret: str, prompt: str, timestamp: str, request_id: str, user_id: str) -> str:
    """Generate frontend-compatible X-Signature.

    Recovered from prod-fe-1.1.37 `nV()`:
      prompt_b64 = btoa(TextEncoder().encode(prompt))
      message = sortedPayload + "|" + prompt_b64 + "|" + timestamp
      bucket = floor(timestamp / 300000)
      key_hex = sha256.hmac(secret, String(bucket))
      signature = sha256.hmac(key_hex, message).toString()

    Important: js-sha256 `.hmac()` returns a hex string, and the second HMAC
    uses that hex string as the key, not raw digest bytes.
    """
    bucket = str(int(int(timestamp) // 300000))
    key_hex = hmac.new(secret.encode(), bucket.encode(), hashlib.sha256).hexdigest()
    prompt_b64 = base64.b64encode(prompt.encode()).decode()
    message = f"{sorted_payload(timestamp, request_id, user_id)}|{prompt_b64}|{timestamp}"
    return hmac.new(key_hex.encode(), message.encode(), hashlib.sha256).hexdigest()


def load_latest_captured_signature() -> Optional[Dict[str, str]]:
    if not CAPTURED_REQUEST_FILE.exists():
        return None
    try:
        data = json.loads(CAPTURED_REQUEST_FILE.read_text())
        requests = data.get("requests") or []
        if not requests:
            return None
        req = requests[-1]
        headers = {str(k).lower(): v for k, v in (req.get("headers") or {}).items()}
        sig = headers.get("x-signature")
        url = req.get("url") or ""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        sig_ts = (q.get("signature_timestamp") or [str(req.get("timestamp") or "")])[0]
        if sig:
            return {"signature": sig, "signature_timestamp": sig_ts, "source": "captured_request.json"}
    except Exception:
        return None
    return None


def load_signature_cache(max_age_seconds: int = 300) -> Optional[Dict[str, str]]:
    if not SIGNATURE_CACHE_FILE.exists():
        captured = load_latest_captured_signature()
        return captured
    try:
        data = json.loads(SIGNATURE_CACHE_FILE.read_text())
        created = float(data.get("created_at") or 0)
        if max_age_seconds > 0 and time.time() - created > max_age_seconds:
            return None
        if data.get("signature") and data.get("signature_timestamp"):
            data.setdefault("source", "zaibot_signature_cache.json")
            return data
    except Exception:
        return None
    return None


def save_signature_cache(signature: str, signature_timestamp: str, source: str = "manual") -> None:
    SIGNATURE_CACHE_FILE.write_text(json.dumps({
        "signature": signature,
        "signature_timestamp": signature_timestamp,
        "created_at": time.time(),
        "source": source,
    }, indent=2), encoding="utf-8")


def get_signature(prompt: str, timestamp: str, request_id: str, user_id: str, *, allow_stale: bool = False) -> Tuple[str, str, str]:
    secret = os.environ.get("ZAIBOT_HMAC_SECRET", "").strip()
    if secret:
        return sign_with_secret(secret, prompt, timestamp, request_id, user_id), timestamp, "local_hmac_secret"

    # Fallback to cache for diff/debug if the frontend rotates the secret.
    max_age = 0 if allow_stale else 300
    cached = load_signature_cache(max_age_seconds=max_age)
    if cached:
        return cached["signature"], cached["signature_timestamp"], cached.get("source", "cache")

    raise ZaibotError(
        "没有可用 X-Signature: 请设置环境变量 ZAIBOT_HMAC_SECRET，"
        "或确保签名缓存文件存在且未过期。"
    )


def load_captcha_cache(max_age_seconds: int = 240) -> Optional[str]:
    if not CAPTCHA_CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CAPTCHA_CACHE_FILE.read_text())
        created = float(data.get("timestamp") or data.get("created_at") or 0)
        if max_age_seconds > 0 and time.time() - created > max_age_seconds:
            return None
        raw = data.get("raw") or data.get("captcha_verify_param")
        if raw:
            return raw
    except Exception:
        return None
    return None


def _default_fingerprint() -> Dict[str, str]:
    """Fallback fingerprint used when no live browser is available.

    Kept for backwards compatibility with single-account CLI usage that
    doesn't go through CaptchaSession.
    """
    return {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "language": "en-US",
        "languages": "en-US,en",
        "timezone": DEFAULT_TIMEZONE,
        "cookie_enabled": "true",
        "screen_width": "1440",
        "screen_height": "900",
        "screen_resolution": "1440x900",
        "viewport_height": "684",
        "viewport_width": "1440",
        "viewport_size": "1440x684",
        "color_depth": "30",
        "pixel_ratio": "1",
        "current_url": "https://chat.z.ai/",
        "pathname": "/",
        "search": "",
        "hash": "",
        "host": "chat.z.ai",
        "hostname": "chat.z.ai",
        "protocol": "https:",
        "referrer": "",
        "title": "Z.ai - Free AI Chatbot & Agent powered by GLM-5.1 & GLM-5",
        "timezone_offset": "-480",
        "local_time": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "utc_time": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime()),
        "is_mobile": "false",
        "is_touch": "false",
        "max_touch_points": "0",
        "browser_name": "Chrome",
        "os_name": "Mac OS",
    }


def build_query_params(token: str, user_id: str, timestamp: str, request_id: str, signature_timestamp: str, *, full_fingerprint: bool = True, fingerprint: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    params = {
        "timestamp": timestamp,
        "requestId": request_id,
        "user_id": user_id,
        "version": "0.0.1",
        "platform": "web",
        "token": token,
        "signature_timestamp": signature_timestamp,
    }
    if full_fingerprint:
        fp = dict(_default_fingerprint())
        if fingerprint:
            fp.update({k: v for k, v in fingerprint.items() if v not in (None, "")})
        # Always refresh time-bound fields even with a provided fingerprint.
        fp["local_time"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        fp["utc_time"] = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
        params.update(fp)
    return params


def build_body(prompt: str, *, model: str = DEFAULT_MODEL, stream: bool = True, captcha_verify_param: Optional[str] = None, enable_thinking: bool = False, chat_id: Optional[str] = None, parent_id: Optional[str] = None, assistant_id: Optional[str] = None, variables: Optional[Dict[str, str]] = None) -> Tuple[Dict[str, Any], str]:
    """Build the request body for chat completions.

    Returns (body_dict, assistant_id) so the caller can track the assistant
    message ID for chaining in a ChatSession.

    `variables` is a partial override of the user-facing template variables
    (e.g. {{USER_LANGUAGE}}). Anything not provided falls back to neutral
    defaults; the values feed the upstream prompt template, NOT the signature
    payload, so changing them does not invalidate X-Signature.
    """
    chat_id = chat_id or new_id()
    assistant_id = assistant_id or new_id()
    user_message_id = new_id()
    base_variables: Dict[str, str] = {
        "{{USER_NAME}}": "",
        "{{USER_LOCATION}}": "Unknown",
        "{{CURRENT_DATETIME}}": time.strftime("%Y-%m-%d %H:%M:%S"),
        "{{CURRENT_DATE}}": time.strftime("%Y-%m-%d"),
        "{{CURRENT_TIME}}": time.strftime("%H:%M:%S"),
        "{{CURRENT_WEEKDAY}}": time.strftime("%A"),
        "{{CURRENT_TIMEZONE}}": DEFAULT_TIMEZONE,
        "{{USER_LANGUAGE}}": "en-US",
    }
    if variables:
        base_variables.update(variables)
    body: Dict[str, Any] = {
        "stream": stream,
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "signature_prompt": prompt,
        "params": {},
        "extra": {},
        "features": {
            "image_generation": False,
            "web_search": False,
            "auto_web_search": False,
            "preview_mode": True,
            "flags": [],
            "vlm_tools_enable": False,
            "vlm_web_search_enable": False,
            "vlm_website_mode": False,
            "enable_thinking": enable_thinking,
        },
        "variables": base_variables,
        "chat_id": chat_id,
        "id": assistant_id,
        "current_user_message_id": user_message_id,
        "current_user_message_parent_id": parent_id,
        "background_tasks": {"title_generation": True, "tags_generation": True},
    }
    if captcha_verify_param:
        body["captcha_verify_param"] = captcha_verify_param
    return body, assistant_id


def detect_user_language(text: str) -> str:
    """Heuristic: any CJK character (Han / Hiragana / Katakana / Hangul) maps
    to "zh-CN", otherwise "en-US".

    Z.ai's upstream template switches task-language based on {{USER_LANGUAGE}};
    this lets us route CJK user prompts to the CJK template branch without
    relying on the client to send a header. Note: Japanese / Korean text is
    also routed to "zh-CN" because the upstream only exposes a CN/EN split;
    if a ja-JP / ko-KR template is added later, refine the ranges here.
    """
    if not text:
        return "en-US"
    for ch in text:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF) or (0x3040 <= cp <= 0x30FF) or (0xAC00 <= cp <= 0xD7AF):
            return "zh-CN"
    return "en-US"


def load_cookie_header(domain_suffix: str = "chat.z.ai") -> str:
    """Build Cookie header from Playwright storage_state.

    Browser fetch includes same-origin cookies implicitly; our urllib request must
    add them explicitly so captcha/device/session binding matches the saved login.
    """
    if not STATE_FILE.exists():
        return ""
    try:
        state = json.loads(STATE_FILE.read_text())
    except Exception:
        return ""
    pairs = []
    for c in state.get("cookies", []):
        domain = str(c.get("domain", "")).lstrip(".")
        if domain == domain_suffix or domain.endswith("." + domain_suffix):
            name = c.get("name")
            value = c.get("value")
            if name is not None and value is not None:
                pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def load_cookie_header_from_state(state_path: Path, domain_suffix: str = "chat.z.ai") -> str:
    """Build Cookie header from a specific state file (per-account support)."""
    if not state_path.exists():
        return ""
    try:
        state = json.loads(state_path.read_text())
    except Exception:
        return ""
    pairs = []
    for c in state.get("cookies", []):
        domain = str(c.get("domain", "")).lstrip(".")
        if domain == domain_suffix or domain.endswith("." + domain_suffix):
            name = c.get("name")
            value = c.get("value")
            if name is not None and value is not None:
                pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _fe_version_header_value() -> str:
    """X-FE-Version header value (always includes the 'prod-fe-' prefix).

    The current frontend bundle (prod-fe-1.1.42) sends the prefix, so we
    must too. Sending a bare '1.1.x' is a fingerprint miss.
    """
    v = FE_VERSION
    if not v.startswith("prod-fe-"):
        v = "prod-fe-" + v
    return v


def _build_headers_internal(token: str, signature: str, cookie: str, fingerprint: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    fp = fingerprint or {}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
        "Accept-Language": fp.get("language") or "en-US",
        "Origin": "https://chat.z.ai",
        "Referer": "https://chat.z.ai/",
        "User-Agent": fp.get("user_agent") or _default_fingerprint()["user_agent"],
        "X-FE-Version": _fe_version_header_value(),
        "X-Region": "overseas",
        "X-Signature": signature,
    }
    # Client Hints — sent by Chrome automatically; without them a request
    # claiming a Chrome UA looks botty and Aliyun captcha `verify_failed`.
    if fp.get("sec_ch_ua"):
        headers["Sec-CH-UA"] = fp["sec_ch_ua"]
        headers["Sec-CH-UA-Mobile"] = fp.get("sec_ch_ua_mobile") or "?0"
        headers["Sec-CH-UA-Platform"] = fp.get("sec_ch_ua_platform") or '"macOS"'
    if cookie:
        headers["Cookie"] = cookie
    return headers


def build_headers_with_cookie(token: str, signature: str, cookie: str, fingerprint: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Variant of build_headers that takes an explicit Cookie header (per-account support)."""
    return _build_headers_internal(token, signature, cookie, fingerprint)


def build_headers(token: str, signature: str, fingerprint: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    cookie = load_cookie_header("chat.z.ai")
    return _build_headers_internal(token, signature, cookie, fingerprint)


def classify_error(status: int, body: str) -> str:
    text = (body or "").lower()
    if status in (401, 403) and any(x in text for x in ["token", "jwt", "auth", "unauthorized", "forbidden"]):
        return "token/login 失效"
    if any(x in text for x in ["captcha", "certify", "securitytoken", "f019", "verify"]):
        return "captcha_verify_param 失效或缺失"
    if any(x in text for x in ["signature", "x-signature", "sign"]):
        return "X-Signature 失效或签名参数不匹配"
    if status == 429 or status == 405 or "rate" in text or "<title>405</title>" in text:
        return "限流"
    # SSE 流中上游 5xx 也会以 status=200 出现，靠 body 文本/code 字段识别。
    if status >= 500 or any(x in text for x in [
        "internal_error", "service_unavailable", "bad_gateway",
        "oops, something went wrong", "please try again later",
    ]):
        return "服务端错误"
    return "未知错误"


def is_retriable_error(kind: str) -> bool:
    """Whether the error is worth retrying with a fresh captcha."""
    retriable = ["captcha", "验证码", "限流", "服务端错误"]
    return any(k in kind for k in retriable)


def _extract_error_payload(obj: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("error"), dict):
        return obj["error"]
    data = obj.get("data")
    if isinstance(data, dict):
        return _extract_error_payload(data)
    return None


def parse_sse_lines(lines: Iterable[bytes], *, echo: bool = True) -> str:
    result = []
    last_error = None
    for raw in lines:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line or line == "data: [DONE]":
            continue
        if not line.startswith("data: "):
            continue
        try:
            data = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        err = _extract_error_payload(data)
        if err:
            last_error = err
            continue
        payload = data.get("data", {}) if isinstance(data, dict) else {}
        if isinstance(payload, str):
            continue
        if isinstance(payload, dict) and payload.get("phase") == "answer" and payload.get("delta_content"):
            chunk = payload["delta_content"]
            result.append(chunk)
            if echo:
                print(chunk, end="", flush=True)
    if echo and result:
        print()
    if not result and last_error:
        body = json.dumps(last_error, ensure_ascii=False)
        raise ZaibotAPIError(classify_error(200, body), body)
    return "".join(result)


def create_chat(model: str = DEFAULT_MODEL) -> str:
    token = read_token()
    chat_id = new_id()
    chat = {
        "id": chat_id,
        "title": "New Chat",
        "models": [model],
        "params": {},
        "history": {"messages": {}, "currentId": ""},
        "messages": [],
        "tags": [],
        "timestamp": int(time.time()),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Language": "en-US",
        "Origin": "https://chat.z.ai",
        "Referer": "https://chat.z.ai/",
    }
    cookie = load_cookie_header("chat.z.ai")
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(
        f"{API_BASE}/v1/chats/new",
        data=json.dumps({"chat": chat, "bot_id": None}, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("id") or chat_id
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise ZaibotHTTPError(e.code, body, f"{API_BASE}/v1/chats/new") from None


def create_chat_with_token(token: str, cookie: str, model: str = DEFAULT_MODEL) -> str:
    """Variant of create_chat that takes explicit token and cookie (per-account support)."""
    chat_id = new_id()
    chat = {
        "id": chat_id,
        "title": "New Chat",
        "models": [model],
        "params": {},
        "history": {"messages": {}, "currentId": ""},
        "messages": [],
        "tags": [],
        "timestamp": int(time.time()),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Language": "en-US",
        "Origin": "https://chat.z.ai",
        "Referer": "https://chat.z.ai/",
    }
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(
        f"{API_BASE}/v1/chats/new",
        data=json.dumps({"chat": chat, "bot_id": None}, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("id") or chat_id
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise ZaibotHTTPError(e.code, body, f"{API_BASE}/v1/chats/new") from None


def post_chat(prompt: str, *, model: str = DEFAULT_MODEL, stream: bool = True, captcha_verify_param: Optional[str] = None, allow_stale_signature: bool = False, full_fingerprint: bool = True, echo: bool = True, session: Optional[ChatSession] = None) -> str:
    token = read_token()
    user_id = get_user_id(token)
    if not user_id:
        raise ZaibotError("无法从 JWT 解析 user_id，请检查 zaibot_token.txt")

    timestamp = now_ms()
    request_id = new_id()
    signature, signature_timestamp, sig_source = get_signature(
        prompt, timestamp, request_id, user_id, allow_stale=allow_stale_signature
    )

    # Determine chat_id: reuse from session or create new
    if session and session.chat_id:
        chat_id = session.chat_id
    else:
        chat_id = create_chat(model)
        if session:
            session.chat_id = chat_id

    # Determine parent_id from session
    parent_id = session.last_assistant_id if session else None

    body_dict, assistant_id = build_body(
        prompt, model=model, stream=stream,
        captcha_verify_param=captcha_verify_param,
        chat_id=chat_id, parent_id=parent_id,
        variables={"{{USER_LANGUAGE}}": detect_user_language(prompt)},
    )

    params = build_query_params(token, user_id, timestamp, request_id, signature_timestamp, full_fingerprint=full_fingerprint)
    url = f"{API_BASE}/v2/chat/completions?{urllib.parse.urlencode(params)}"
    body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=build_headers(token, signature), method="POST")

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            content_type = (resp.headers.get("content-type") or "").lower()
            if stream or "text/event-stream" in content_type:
                result = parse_sse_lines(resp, echo=echo)
            else:
                raw = resp.read()
                data = json.loads(raw)
                err = _extract_error_payload(data)
                if err:
                    body_text = json.dumps(err, ensure_ascii=False)
                    raise ZaibotAPIError(classify_error(200, body_text), body_text)
                result = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Update session state after successful response
        if session:
            session.last_assistant_id = assistant_id

        return result
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise ZaibotHTTPError(e.code, err_body, url) from None
