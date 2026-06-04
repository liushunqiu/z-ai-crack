#!/usr/bin/env python3
"""Camoufox-based captcha service for Z.ai.

Uses Camoufox anti-detection browser to run the full TRACELESS captcha flow:
  InitCaptchaV3 -> FeiLin getToken() -> VerifyCaptchaV3 -> securityToken

Returns captcha_verify_param (base64-encoded JSON with certifyId, sceneId, isSign, securityToken).
"""
from __future__ import annotations

import base64
import json
import queue
import sys
import time
from pathlib import Path
import threading
from concurrent.futures import Future

BASE_DIR = Path(__file__).parent
CACHE_FILE = BASE_DIR / "zaibot_captcha_cache.json"
STATE_FILE = BASE_DIR / "zaibot_state.json"
SCENE_ID = "didk33e0"


def _trigger_captcha_flow(page, *, click_send: bool = True, max_retries: int = 15) -> tuple:
    """Trigger captcha flow on an already-loaded page and return (certify_id, security_token).

    Fixed 10s timeout per attempt, no sleep between retries.
    """
    # Prepare input
    page.evaluate("""() => {
        const ta = document.getElementById('chat-input');
        if (!ta) throw new Error('chat-input not found');
        ta.focus();
        const nativeSetter = Object.getOwnPropertyDescriptor(
            HTMLTextAreaElement.prototype, 'value'
        ).set;
        nativeSetter.call(ta, 'hello');
        ta.dispatchEvent(new Event('input', { bubbles: true }));
        ta.dispatchEvent(new Event('change', { bubbles: true }));
    }""")
    time.sleep(1)

    certify_id = None
    security_token = None

    for attempt in range(max_retries):
        try:
            with page.expect_response(
                lambda r: "captcha-open-southeast" in r.url or "captcha-open-ga" in r.url,
                timeout=10000,
            ) as resp_info:
                if attempt == 0 and click_send:
                    page.evaluate("""() => {
                        const btn = document.getElementById('send-message-button');
                        if (!btn) throw new Error('send button not found');
                        if (btn.disabled) throw new Error('send button still disabled');
                        btn.click();
                    }""")

            response = resp_info.value
            body = response.json()
            result = body.get("Result", {})

            if result.get("securityToken"):
                certify_id = result.get("certifyId")
                security_token = result["securityToken"]
                print(f"[✓] Got securityToken! certifyId={certify_id}", file=sys.stderr)
                break

            if body.get("CaptchaType") and body.get("CertifyId"):
                certify_id = body["CertifyId"]
                print(f"[*] Got InitCaptchaV3: certifyId={certify_id}, type={body['CaptchaType']}", file=sys.stderr)

        except Exception as e:
            err_str = str(e)
            if "Timeout" in err_str or "timeout" in err_str:
                print(f"[*] Attempt {attempt + 1}/{max_retries}: timeout", file=sys.stderr)
                continue
            print(f"[!] Attempt {attempt + 1}: unexpected error: {e}", file=sys.stderr)
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


def get_captcha_verify_param(headless: bool = True, save: bool = True, timeout: int = 45) -> str:
    """Run the full captcha flow in Camoufox and return captcha_verify_param."""
    from camoufox import Camoufox

    if not STATE_FILE.exists():
        raise RuntimeError(f"Login state not found: {STATE_FILE}. Run 'python login.py login' first.")

    state = json.loads(STATE_FILE.read_text())

    print(f"[*] Launching Camoufox (headless={headless})...", file=sys.stderr)
    with Camoufox(headless=headless, geoip=False) as browser:
        context = browser.new_context(storage_state=state)
        page = context.new_page()

        print(f"[*] Navigating to chat.z.ai...", file=sys.stderr)
        page.goto("https://chat.z.ai/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("#chat-input", timeout=15000)
        print(f"[*] Page ready: {page.title()}", file=sys.stderr)

        print(f"[*] Sending message and waiting for captcha responses...", file=sys.stderr)
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
    ):
        self.headless = headless
        self.state_path: Path = state_path or STATE_FILE
        self.token_path: Path = token_path or (BASE_DIR / "zaibot_token.txt")
        self.captcha_cache_path: Path = captcha_cache_path or CACHE_FILE
        self._browser_ctx = None
        self._browser = None
        self._context = None
        self._fetch_page = None
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
        print(f"[*] Launching persistent Camoufox (headless={self.headless}, state={self.state_path})...", file=sys.stderr)

        self._browser_ctx = Camoufox(headless=self.headless, geoip=False)
        self._browser = self._browser_ctx.__enter__()
        self._context = self._browser.new_context(storage_state=state)
        print(f"[*] Persistent browser ready.", file=sys.stderr)

    def interactive_login(self, *, on_progress=None) -> bool:
        """Headful login flow: open chat.z.ai and wait for user to complete login.

        Returns True on success (token captured in localStorage), False otherwise.
        Calls on_progress(status: str) for UI feedback.

        The browser stays open and persistent so subsequent captcha calls can
        reuse it. Must be called after start().
        """
        if not self._context:
            raise RuntimeError("Session not started. Call start() first.")

        return self._run_on_worker(self._interactive_login_impl, on_progress)

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

    def get_captcha(self, save: bool = True) -> str:
        """Get a fresh captcha token. Runs on the dedicated worker thread."""
        return self._run_on_worker(self._get_captcha_impl, save)

    def _get_captcha_impl(self, save: bool) -> str:
        if not self._context:
            raise RuntimeError("Session not started. Call start() first.")

        print(f"[*] Getting fresh captcha token (new tab)...", file=sys.stderr)

        page = self._context.new_page()
        try:
            page.goto("https://chat.z.ai/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("#chat-input", timeout=15000)

            certify_id, security_token = _trigger_captcha_flow(page)
        finally:
            page.close()

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

        return raw

    def get_fetch_page(self):
        """Get or create a persistent page on chat.z.ai for fetch requests."""
        if self._fetch_page is not None:
            try:
                _ = self._fetch_page.url  # check if page is still alive
                return self._fetch_page
            except Exception:
                self._fetch_page = None

        page = self._context.new_page()
        page.goto("https://chat.z.ai/", wait_until="domcontentloaded", timeout=30000)
        self._fetch_page = page
        print(f"[*] Persistent fetch page ready.", file=sys.stderr)
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
        """Streaming fetch: yield {status, chunk, done, error} dicts.

        The initial JS setup runs on the worker thread. Then we poll from the
        calling thread — page.evaluate for polling is safe because it only
        reads a JS global (no greenlet-sensitive operations).
        """
        # Start the JS streaming fetch on the worker thread
        self._run_on_worker(self._start_streaming_fetch, url, headers, body)

        # Poll from the calling thread (page.evaluate for polling is safe —
        # it just reads a JS global array, no navigation or page creation)
        while True:
            items = self._run_on_worker(self._poll_stream_buffer)

            for item in items["items"]:
                yield item

            if items["done"]:
                if items["error"]:
                    raise RuntimeError(items["error"])
                break

            time.sleep(0.05)  # 50ms 轮询间隔

    def _start_streaming_fetch(self, url: str, headers: dict, body: str):
        page = self.get_fetch_page()
        page.evaluate('''([url, headers, body]) => {
            window.__stream_buf = [];
            window.__stream_done = false;
            window.__stream_error = null;
            (async () => {
                try {
                    const resp = await fetch(url, {
                        method: "POST",
                        headers: headers,
                        body: body,
                    });
                    window.__stream_buf.push({status: resp.status, type: "status"});

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
                    window.__stream_error = e.message;
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
    print(f"[*] Starting captcha service (headless={headless})...", file=sys.stderr)
    try:
        result = get_captcha_verify_param(headless=headless)
        decoded = json.loads(base64.b64decode(result))
        print(f"[✓] captcha_verify_param obtained", file=sys.stderr)
        print(f"    certifyId: {decoded['certifyId']}", file=sys.stderr)
        print(f"    securityToken: {decoded['securityToken'][:40]}...", file=sys.stderr)
        print(result)
    except Exception as e:
        print(f"[x] Failed: {e}", file=sys.stderr)
        sys.exit(1)
