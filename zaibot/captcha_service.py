#!/usr/bin/env python3
"""Camoufox-based captcha service for Z.ai.

Uses Camoufox anti-detection browser to run the full TRACELESS captcha flow:
  InitCaptchaV3 -> FeiLin getToken() -> VerifyCaptchaV3 -> securityToken

Returns captcha_verify_param (base64-encoded JSON with certifyId, sceneId, isSign, securityToken).
"""
from __future__ import annotations
import logging
import queue

import base64
import json
import sys
import time
from pathlib import Path
import threading
from concurrent.futures import Future
from typing import Optional, Tuple

BASE_DIR = Path(__file__).parent
CACHE_FILE = BASE_DIR / "zaibot_captcha_cache.json"
STATE_FILE = BASE_DIR / "zaibot_state.json"
SCENE_ID = "didk33e0"


_logger = logging.getLogger(__name__)

def _trigger_captcha_flow(page, *, click_send: bool = True, max_retries: int = 15) -> tuple:
    """Trigger captcha flow on an already-loaded page and return (certify_id, security_token).

    Simulates human-like interaction to avoid Aliyun Anti-Bot behavior scoring:
      - Random warmup pause (page just loaded, real users take a beat)
      - Focus textarea, then real keystrokes with jittered per-char delays
      - "Thinking" pause after typing (real users hesitate before clicking send)
      - Curved mouse path with a few waypoints, then real mouse click
    """
    import random

    # Warmup: page just loaded, real user takes a moment to orient
    warmup = random.uniform(0.4, 1.2)
    time.sleep(warmup)

    # Focus the textarea via real click so React picks up focus events
    ta_box = page.evaluate("""() => {
        const ta = document.getElementById('chat-input');
        if (!ta) throw new Error('chat-input not found');
        ta.focus();
        const r = ta.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }""")
    # A real user would mouse over to the textarea before typing
    page.mouse.move(ta_box["x"] - random.uniform(20, 60), ta_box["y"] - random.uniform(10, 30), steps=8)
    time.sleep(random.uniform(0.1, 0.25))
    page.mouse.click(ta_box["x"], ta_box["y"])
    time.sleep(random.uniform(0.1, 0.3))

    # Type a short warmup string character-by-character with jittered delays.
    # Real keystrokes trigger React's onChange and any custom input handlers.
    text = "hi"
    for ch in text:
        page.keyboard.press(ch)
        time.sleep(random.uniform(0.06, 0.18))

    think = random.uniform(2.5, 5.0)
    _logger.info(f"[*] thinking {think:.2f}s before send")
    time.sleep(think)

    certify_id = None
    security_token = None

    for attempt in range(max_retries):
        try:
            with page.expect_response(
                lambda r: "captcha-open-southeast" in r.url or "captcha-open-ga" in r.url,
                timeout=10000,
            ) as resp_info:
                if attempt == 0 and click_send:
                    # Curved mouse path to the send button, then real click
                    # 修: button 可能暂时 disabled (React state 还没更新),
                    # 等 1.5s 再点一次, 最多 3 次
                    clicked = False
                    for click_try in range(3):
                        try:
                            btn_pos = page.evaluate("""() => {
                                const btn = document.getElementById('send-message-button');
                                if (!btn) return null;
                                if (btn.disabled) return { disabled: true };
                                const r = btn.getBoundingClientRect();
                                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                            }""")
                            if btn_pos is None:
                                raise RuntimeError("send button not found")
                            if btn_pos.get("disabled"):
                                _logger.info(f"[*] send button disabled, 等待 1.5s 后重试 ({click_try + 1}/3)")
                                time.sleep(1.5)
                                continue
                            tx, ty = btn_pos["x"], btn_pos["y"]
                            # Pick a start point a bit away from current mouse position
                            sx = ta_box["x"] + random.uniform(-20, 20)
                            sy = ta_box["y"] + random.uniform(-20, 20)
                            # 4 waypoints with perpendicular jitter for a curved path
                            for step in range(1, 5):
                                t = step / 4
                                jit = 1 - abs(t - 0.5) * 2
                                ox = random.uniform(-12, 12) * jit
                                oy = random.uniform(-12, 12) * jit
                                mx = sx + (tx - sx) * t + ox
                                my = sy + (ty - sy) * t + oy
                                page.mouse.move(mx, my, steps=4)
                                time.sleep(random.uniform(0.02, 0.06))
                            time.sleep(random.uniform(0.05, 0.18))
                            page.mouse.click(tx, ty)
                            clicked = True
                            break
                        except RuntimeError as e:
                            if "not found" in str(e):
                                raise  # 真的找不到, 不要再试
                            _logger.info(f"[*] send button click 失败: {e}, 重试")
                            time.sleep(1.0)
                    if not clicked:
                        raise RuntimeError("send button 持续 disabled, 跳过 captcha")

            response = resp_info.value
            body = response.json()
            result = body.get("Result", {})

            if result.get("securityToken"):
                certify_id = result.get("certifyId")
                security_token = result["securityToken"]
                _logger.info(f"[✓] Got securityToken! certifyId={certify_id}")
                break

            if body.get("CaptchaType") and body.get("CertifyId"):
                certify_id = body["CertifyId"]
                _logger.info(f"[*] Got InitCaptchaV3: certifyId={certify_id}, type={body['CaptchaType']}")

        except Exception as e:
            err_str = str(e)
            if "Timeout" in err_str or "timeout" in err_str:
                _logger.info(f"[*] Attempt {attempt + 1}/{max_retries}: timeout")
                continue
            _logger.warning(f"[!] Attempt {attempt + 1}: unexpected error: {e}")
            raise

    if not security_token:
        raise RuntimeError(f"Failed to get securityToken after {max_retries} attempts")

    return certify_id, security_token


def _build_captcha_raw(certify_id: str, security_token: str) -> tuple:
    param_obj = {
        "certifyId": certify_id,
        "sceneId": SCENE_ID,
        "isSign": True,
        "securityToken": security_token,
    }
    return base64.b64encode(json.dumps(param_obj).encode()).decode(), param_obj


_FINGERPRINT_JS = r"""() => {
    const uaData = navigator.userAgentData;
    const brands = uaData && Array.isArray(uaData.brands)
        ? uaData.brands.map(b => '"' + b.brand + '";v="' + b.version + '"').join(', ')
        : '';
    const platform = uaData && uaData.platform ? '"' + uaData.platform + '"' : '';
    const mobile = uaData && typeof uaData.mobile === 'boolean' ? '?' + (uaData.mobile ? '1' : '0') : '?0';
    const ua = navigator.userAgent;
    const browserName = (function () {
        if (/Edg\//.test(ua)) return 'Edge';
        if (/Chrome\//.test(ua)) return 'Chrome';
        if (/Firefox\//.test(ua)) return 'Firefox';
        if (/Safari\//.test(ua) && !/Chrome\//.test(ua)) return 'Safari';
        return 'Chrome';
    })();
    const osName = (function () {
        if (/Windows NT/.test(ua)) return 'Windows';
        if (/Mac OS X/.test(ua)) return 'Mac OS';
        if (/Android/.test(ua)) return 'Android';
        if (/iPhone|iPad|iPod/.test(ua)) return 'iOS';
        if (/Linux/.test(ua)) return 'Linux';
        return 'Unknown';
    })();
    const lang = navigator.language || 'en-US';
    const langs = (navigator.languages && navigator.languages.length)
        ? navigator.languages.join(',')
        : lang;
    return {
        user_agent: ua,
        language: lang,
        languages: langs,
        timezone: (Intl.DateTimeFormat().resolvedOptions().timeZone) || '',
        cookie_enabled: String(navigator.cookieEnabled),
        screen_width: String(window.screen.width),
        screen_height: String(window.screen.height),
        screen_resolution: window.screen.width + 'x' + window.screen.height,
        viewport_height: String(window.innerHeight),
        viewport_width: String(window.innerWidth),
        viewport_size: window.innerWidth + 'x' + window.innerHeight,
        color_depth: String(window.screen.colorDepth || 24),
        pixel_ratio: String(window.devicePixelRatio || 1),
        current_url: window.location.href,
        pathname: window.location.pathname,
        search: window.location.search,
        hash: window.location.hash,
        host: window.location.host,
        hostname: window.location.hostname,
        protocol: window.location.protocol,
        referrer: document.referrer,
        title: document.title,
        timezone_offset: String(new Date().getTimezoneOffset()),
        local_time: new Date().toString(),
        utc_time: new Date().toUTCString(),
        is_mobile: /Mobile|Android|iPhone|iPad/.test(ua) ? 'true' : 'false',
        is_touch: String('ontouchstart' in window),
        max_touch_points: String(navigator.maxTouchPoints || 0),
        browser_name: browserName,
        os_name: osName,
        sec_ch_ua: brands,
        sec_ch_ua_mobile: mobile,
        sec_ch_ua_platform: platform,
    };
}"""


def _collect_fingerprint(page) -> dict:
    """Collect the browser fingerprint that the captcha `data` field is bound to.

    The Aliyun captcha `data` payload is an AES-encrypted fingerprint digest
    (see captured_data_fields.json). Z.ai/Aliyun verify this against the
    fingerprint sent on the chat-completion request, so the urllib caller
    MUST submit the same values the Camoufox browser reported.
    """
    return page.evaluate(_FINGERPRINT_JS)


def get_captcha_verify_param(headless: bool = True, save: bool = True, timeout: int = 45) -> str:
    """Run the full captcha flow in Camoufox and return captcha_verify_param."""
    from camoufox import Camoufox

    if not STATE_FILE.exists():
        raise RuntimeError(f"Login state not found: {STATE_FILE}. Run 'python login.py login' first.")

    state = json.loads(STATE_FILE.read_text())

    _logger.info(f"[*] Launching Camoufox (headless={headless})...")
    with Camoufox(headless=headless, geoip=False) as browser:
        context = browser.new_context(storage_state=state)
        page = context.new_page()

        _logger.info(f"[*] Navigating to chat.z.ai...")
        page.goto("https://chat.z.ai/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("#chat-input", timeout=15000)
        _logger.info(f"[*] Page ready: {page.title()}")

        _logger.info(f"[*] Sending message and waiting for captcha responses...")
        certify_id, security_token = _trigger_captcha_flow(page)

        raw, param_obj = _build_captcha_raw(certify_id, security_token)

        if save:
            CACHE_FILE.write_text(
                json.dumps(
                    {
                        "raw": raw,
                        "decoded": param_obj,
                        "timestamp": time.time(),
                        "source": "captcha_service.py",
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        return raw


class CaptchaSession:
    """Persistent browser session for repeated captcha token generation.

    All Playwright operations run on a dedicated worker thread to avoid
    greenlet "Cannot switch to a different thread" errors when called from
    FastAPI's thread pool executor.

    Each instance is bound to a specific state file (storage_state.json) and
    captcha cache file. Pass state_path/token_path to use a non-default
    account; defaults to the legacy single-account files.

    Usage:
        with CaptchaSession(headless=True) as session:
            token1 = session.get_captcha()
            token2 = session.get_captcha()  # reuses browser, new tab
    """

    def __init__(
        self,
        headless: bool = True,
        *,
        state_path: Path | None = None,
        token_path: Path | None = None,
        captcha_cache_path: Path | None = None,
        # 新增：账号标识，用于生成独立指纹
        account_id: str | None = None,
        account_name: str | None = None,
    ):
        self.headless = headless
        self.state_path: Path = state_path or STATE_FILE
        self.token_path: Path = token_path or (BASE_DIR / "zaibot_token.txt")
        self.captcha_cache_path: Path = captcha_cache_path or CACHE_FILE
        self.account_id = account_id
        self.account_name = account_name
        self._browser_ctx = None
        self._browser = None
        self._context = None
        self._fetch_page = None
        self._fingerprint: Optional[dict] = None
        # Per-session captcha rate limit. Aliyun's WAF blocks fast loops
        # (~20 captchas in <30s) with 405; throttle to stay under the cap.
        # Bumped to 4s now that the flow itself is ~1.6-5s of human-like
        # interaction — combined with the throttle, actual inter-captcha
        # gap is ~5.6-9s, which keeps us under Aliyun's behavior threshold.
        # Tune via set_captcha_rate_limit() at runtime if needed.
        self._min_captcha_interval = 6.0
        self._last_captcha_at = 0.0
        # Dedicated thread for ALL Playwright operations
        self._worker_thread: threading.Thread | None = None
        self._task_queue: queue.Queue = queue.Queue()

    def _run_on_worker(self, fn, *args, **kwargs):
        """Dispatch fn to the worker thread and wait for result."""
        if threading.current_thread() is self._worker_thread:
            # Already on worker thread, call directly
            return fn(*args, **kwargs)
        fut: Future = Future()
        self._task_queue.put((fut, fn, args, kwargs))
        result = fut.result()  # blocks until done
        return result

    def _worker_loop(self):
        """Worker thread main loop: process tasks from queue."""
        while True:
            item = self._task_queue.get()
            if item is None:
                break
            fut, fn, args, kwargs = item
            try:
                result = fn(*args, **kwargs)
                fut.set_result(result)
            except Exception as e:
                fut.set_exception(e)

    def start(self):
        """Launch browser (once) on a dedicated worker thread."""
        # Start worker thread first
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

        # Launch browser on the worker thread
        self._run_on_worker(self._start_browser)

    def _start_browser(self):
        from camoufox import Camoufox

        if not self.state_path.exists():
            raise RuntimeError(
                f"Login state not found: {self.state_path}. "
                f"Add the account through the admin UI or run login.py."
            )

        state = json.loads(self.state_path.read_text())
        _logger.info(f"[*] Launching persistent Camoufox (headless={self.headless}, state={self.state_path}, account={self.account_name})...")

        # 为每个账号生成独立的浏览器配置
        # 这样可以避免账号被关联
        config = {
            "headless": self.headless,
            "geoip": False,
        }

        # 根据账号标识生成不同的指纹配置
        if self.account_id:
            # 使用 account_id 的哈希值来生成不同的配置
            # 这样可以确保每个账号的配置是确定性的，但又不同
            import hashlib
            hash_val = int(hashlib.md5(self.account_id.encode()).hexdigest()[:8], 16)

            # 根据哈希值选择不同的配置
            # 操作系统指纹：随机选择 windows/macos/linux
            os_choices = ["windows", "macos", "linux"]
            config["os"] = os_choices[hash_val % len(os_choices)]

            # 语言环境：根据账号选择不同的 locale
            locale_choices = ["zh-CN", "en-US", "ja-JP", "ko-KR"]
            config["locale"] = locale_choices[hash_val % len(locale_choices)]

            # 阻止 WebRTC：根据账号决定
            config["block_webrtc"] = (hash_val % 2 == 0)

            _logger.info(f"[*] Browser config for {self.account_name}: os={config['os']}, locale={config['locale']}, block_webrtc={config['block_webrtc']}")

        self._browser_ctx = Camoufox(**config)
        self._browser = self._browser_ctx.__enter__()
        self._context = self._browser.new_context(storage_state=state)
        _logger.info(f"[*] Persistent browser ready (account={self.account_name}).")

    def _interactive_login_impl(self, on_progress) -> bool:
        page = self._context.new_page()
        try:
            if on_progress:
                on_progress("opening_chat.z.ai")
            page.goto("https://chat.z.ai/", wait_until="domcontentloaded", timeout=60000)

            if on_progress:
                on_progress("waiting_for_login")
            # Poll localStorage.token for up to 5 minutes
            deadline = time.time() + 300
            while time.time() < deadline:
                token = page.evaluate("() => localStorage.getItem('token') || ''")
                token = (token or "").strip().strip('"')
                if token:
                    # Verify user object is also set (login is complete)
                    user = page.evaluate("() => localStorage.getItem('user') || ''")
                    if user and user != "null":
                        # Save state immediately so partial state isn't lost if user closes window
                        storage = self._context.storage_state()
                        self.state_path.parent.mkdir(parents=True, exist_ok=True)
                        self.state_path.write_text(json.dumps(storage, ensure_ascii=False, indent=2), encoding="utf-8")
                        if on_progress:
                            on_progress("login_succeeded")
                        return True
                time.sleep(2)

            if on_progress:
                on_progress("login_timeout")
            return False
        finally:
            try:
                page.close()
            except Exception:
                pass

    def get_captcha(self, save: bool = True) -> Tuple[str, dict]:
        """Get a fresh captcha token + the browser fingerprint that produced it.

        The fingerprint MUST be forwarded to the chat-completion HTTP request
        so the Aliyun captcha `data` field and the request fingerprint agree.

        Runs on the dedicated worker thread.
        """
        return self._run_on_worker(self._get_captcha_impl, save)

    def _get_captcha_impl(self, save: bool) -> Tuple[str, dict]:
        if not self._context:
            raise RuntimeError("Session not started. Call start() first.")

        _logger.info(f"[*] Getting fresh captcha token (new tab)...")

        # Per-session rate limit: Aliyun's WAF blocks bursts (~20 captchas in
        # <30s) with HTTP 405. Sleep until the minimum interval has elapsed
        # since the previous captcha from this session.
        now = time.time()
        wait = self._last_captcha_at + self._min_captcha_interval - now
        if wait > 0:
            _logger.info(f"[*] captcha rate limit: sleeping {wait:.2f}s (min interval {self._min_captcha_interval}s)")
            time.sleep(wait)

        page = self._context.new_page()
        page.add_init_script(
            "window.__nativeFetch = window.fetch.bind(window);"
        )
        # 关键: 屏蔽 chat.z.ai 前端抛出的未捕获异常,
        # 否则 Playwright 的 FFPage._onUncaughtError 会因为 pageError.location
        # 为 undefined 而整个 Node.js 进程崩溃。
        def _swallow_page_error(err):
            try:
                _logger.warning(f"[!] page error (swallowed): {err}")
            except Exception:
                pass
        page.on("pageerror", _swallow_page_error)
        try:
            page.goto("https://chat.z.ai/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("#chat-input", timeout=15000)

            certify_id, security_token = _trigger_captcha_flow(page)

            # Collect fingerprint from the same page so it's bound to the
            # exact captcha that was just produced.
            if self._fingerprint is None:
                try:
                    self._fingerprint = _collect_fingerprint(page)
                    _logger.info(f"[*] Captured browser fingerprint (ua={self._fingerprint.get('user_agent', '')[:60]}...)")
                except Exception as e:
                    _logger.warning(f"[!] fingerprint collection failed: {e}")
                    self._fingerprint = None
        except Exception:
            try:
                page.close()
            except Exception:
                pass
            raise

        # Reuse the captcha page as the persistent fetch page. This makes the
        # subsequent chat-completion request share the EXACT same page
        # context (URL, referrer, document, React state) that produced the
        # captcha — Aliyun WAF binds the captcha to all of these, so using
        # a fresh page for the fetch causes verify_failed on attempt 0.
        if self._fetch_page is not None:
            try:
                self._fetch_page.close()
            except Exception:
                pass
        self._fetch_page = page
        self._last_captcha_at = time.time()

        raw, param_obj = _build_captcha_raw(certify_id, security_token)

        if save:
            self.captcha_cache_path.write_text(
                json.dumps(
                    {
                        "raw": raw,
                        "decoded": param_obj,
                        "timestamp": time.time(),
                        "source": "captcha_service.py:persistent",
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        return raw, (self._fingerprint or {})

    def set_captcha_rate_limit(self, seconds: float):
        """Override the per-session captcha minimum interval (in seconds)."""
        self._min_captcha_interval = max(0.0, float(seconds))

    def get_fetch_page(self):
        """Get or create a persistent page on chat.z.ai for fetch requests."""
        if self._fetch_page is not None:
            try:
                _ = self._fetch_page.url  # check if page is still alive
                return self._fetch_page
            except Exception:
                self._fetch_page = None

        page = self._context.new_page()
        # Capture native fetch BEFORE chat.z.ai's React wrapper installs.
        # addInitScript runs in the page context before any document scripts.
        page.add_init_script(
            "window.__nativeFetch = window.fetch.bind(window);"
        )
        page.goto("https://chat.z.ai/", wait_until="domcontentloaded", timeout=30000)
        self._fetch_page = page
        _logger.info(f"[*] Persistent fetch page ready (native fetch captured).")
        return page

    def fetch(self, url: str, headers: dict, body: str) -> dict:
        """Execute fetch on the persistent page. Runs on the dedicated worker thread."""
        return self._run_on_worker(self._fetch_impl, url, headers, body)

    def _fetch_impl(self, url: str, headers: dict, body: str) -> dict:
        page = self.get_fetch_page()
        try:
            return page.evaluate('''async ([url, headers, body]) => {
                try {
                    const resp = await fetch(url, {
                        method: 'POST',
                        headers: headers,
                        body: body,
                    });
                    const text = await resp.text();
                    return {status: resp.status, ok: resp.ok, body: text};
                } catch(e) {
                    return {error: e.message};
                }
            }''', [url, headers, body])
        except Exception:
            # Page might have crashed, recreate and retry once
            try:
                self._fetch_page.close()
            except Exception:
                pass
            self._fetch_page = None
            page = self.get_fetch_page()
            return page.evaluate('''async ([url, headers, body]) => {
                try {
                    const resp = await fetch(url, {
                        method: 'POST',
                        headers: headers,
                        body: body,
                    });
                    const text = await resp.text();
                    return {status: resp.status, ok: resp.ok, body: text};
                } catch(e) {
                    return {error: e.message};
                }
            }''', [url, headers, body])

    def fetch_streaming(self, url: str, headers: dict, body: str):
        """Streaming fetch via page.evaluate(native fetch).

        Two changes vs the previous implementation:
        1. Save a reference to native fetch on first call (before any
           chat.z.ai React wrapper is applied) and use that for all
           subsequent calls. The wrapper we observed only forces an
           x-region header, but bypassing it removes one variable.
        2. Capture resp.status / content-type / hasBody into the buffer
           and surface them in the polled dict, so failures surface as
           actionable errors instead of a silent "no chunks" hang.
        """
        # Start the JS streaming fetch on the worker thread (page is owned there)
        self._run_on_worker(self._start_streaming_fetch, url, headers, body)

        # Poll buffer from the worker thread
        while True:
            items = self._run_on_worker(self._poll_stream_buffer)

            for item in items["items"]:
                yield item

            if items["done"]:
                if items["error"]:
                    raise RuntimeError(items["error"])
                break

            time.sleep(0.05)

    def _start_streaming_fetch(self, url: str, headers: dict, body: str):
        page = self.get_fetch_page()
        page.evaluate('''([url, headers, body]) => {
            // Save native fetch on first call so future calls bypass any
            // chat.z.ai React wrapper (window.fetch may be replaced later).
            if (!window.__nativeFetch) {
                window.__nativeFetch = window.fetch.bind(window);
            }
            window.__stream_buf = [];
            window.__stream_done = false;
            window.__stream_error = null;
            window.__stream_status = null;
            (async () => {
                try {
                    const resp = await window.__nativeFetch(url, {
                        method: "POST",
                        headers: headers,
                        body: body,
                    });
                    window.__stream_status = resp.status;
                    window.__stream_buf.push({
                        status: resp.status,
                        type: "status",
                        contentType: resp.headers.get("content-type") || "",
                        hasBody: !!resp.body,
                    });

                    if (!resp.body) {
                        window.__stream_error = "resp.body is null (status=" + resp.status + ")";
                        window.__stream_done = true;
                        return;
                    }

                    const reader = resp.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = "";
                    let flushTimer = null;
                    const FLUSH_INTERVAL = 100;
                    const FLUSH_SIZE = 4096;

                    function flush() {
                        if (buffer.length > 0) {
                            window.__stream_buf.push({chunk: buffer});
                            buffer = "";
                        }
                        if (flushTimer) {
                            clearTimeout(flushTimer);
                            flushTimer = null;
                        }
                    }

                    while (true) {
                        const {done, value} = await reader.read();
                        if (done) break;
                        buffer += decoder.decode(value, {stream: true});
                        if (buffer.length >= FLUSH_SIZE) {
                            flush();
                        } else if (!flushTimer) {
                            flushTimer = setTimeout(flush, FLUSH_INTERVAL);
                        }
                    }
                    flush();
                    window.__stream_done = true;
                } catch(e) {
                    window.__stream_error = (e && e.message) || String(e);
                    window.__stream_done = true;
                }
            })();
        }''', [url, headers, body])

    def _poll_stream_buffer(self):
        page = self.get_fetch_page()
        return page.evaluate('''() => {
            const buf = window.__stream_buf || [];
            window.__stream_buf = [];
            return {
                items: buf,
                done: window.__stream_done || false,
                error: window.__stream_error || null,
                status: window.__stream_status,
            };
        }''')

    def close(self):
        """Clean up browser resources."""
        if self._fetch_page:
            try:
                self._fetch_page.close()
            except Exception:
                pass
            self._fetch_page = None
        if self._browser_ctx:
            try:
                self._browser_ctx.__exit__(None, None, None)
            except Exception:
                pass
            self._browser_ctx = None
            self._browser = None
            self._context = None
        # Stop worker thread
        if self._worker_thread and self._worker_thread.is_alive():
            self._task_queue.put(None)
            self._worker_thread.join(timeout=5)
            self._worker_thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.close()


if __name__ == "__main__":
    headless = "--no-headless" not in sys.argv
    _logger.info(f"[*] Starting captcha service (headless={headless})...")
    try:
        result = get_captcha_verify_param(headless=headless)
        decoded = json.loads(base64.b64decode(result))
        _logger.info(f"[✓] captcha_verify_param obtained")
        _logger.info(f"    certifyId: {decoded['certifyId']}")
        _logger.info(f"    securityToken: {decoded['securityToken'][:40]}...")
        print(result)
    except Exception as e:
        _logger.warning(f"[x] Failed: {e}")
        sys.exit(1)
