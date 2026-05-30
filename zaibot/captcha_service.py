#!/usr/bin/env python3
"""Camoufox-based captcha service for Z.ai.

Uses Camoufox anti-detection browser to run the full TRACELESS captcha flow:
  InitCaptchaV3 -> FeiLin getToken() -> VerifyCaptchaV3 -> securityToken

Returns captcha_verify_param (base64-encoded JSON with certifyId, sceneId, isSign, securityToken).
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
CACHE_FILE = BASE_DIR / "zaibot_captcha_cache.json"
STATE_FILE = BASE_DIR / "zaibot_state.json"
SCENE_ID = "didk33e0"


def _trigger_captcha_flow(page, *, click_send: bool = True, max_retries: int = 10) -> tuple:
    """Trigger captcha flow on an already-loaded page and return (certify_id, security_token).

    Uses exponential backoff: timeout 3s→20s, sleep 2s→10s.
    Default 10 retries, total max wait ~3-4 min.
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
        # Exponential backoff: 3s * 1.5^attempt, capped at 20s
        timeout_sec = min(3.0 * (1.5 ** attempt), 20.0)
        timeout_ms = int(timeout_sec * 1000)

        try:
            with page.expect_response(
                lambda r: "captcha-open-southeast" in r.url or "captcha-open-ga" in r.url,
                timeout=timeout_ms,
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
                print(f"[*] Attempt {attempt + 1}/{max_retries}: timeout ({timeout_sec:.1f}s)", file=sys.stderr)
                # Backoff sleep between retries
                backoff = min(2.0 * (1.5 ** attempt), 10.0)
                time.sleep(backoff)
                continue
            # Non-timeout errors: log and re-raise immediately
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
        time.sleep(2)

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

    The browser stays alive across multiple get_captcha() calls. Each call
    opens a NEW tab (page) for the captcha flow, then closes it. This avoids
    polluting any existing page state.

    Usage:
        with CaptchaSession(headless=True) as session:
            token1 = session.get_captcha()
            token2 = session.get_captcha()  # reuses browser, new tab
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser_ctx = None
        self._browser = None
        self._context = None

    def start(self):
        """Launch browser (once). No navigation yet — tabs are created on demand."""
        from camoufox import Camoufox

        if not STATE_FILE.exists():
            raise RuntimeError(f"Login state not found: {STATE_FILE}. Run 'python login.py login' first.")

        state = json.loads(STATE_FILE.read_text())
        print(f"[*] Launching persistent Camoufox (headless={self.headless})...", file=sys.stderr)

        self._browser_ctx = Camoufox(headless=self.headless, geoip=False)
        self._browser = self._browser_ctx.__enter__()
        self._context = self._browser.new_context(storage_state=state)
        print(f"[*] Persistent browser ready.", file=sys.stderr)

    def get_captcha(self, save: bool = True) -> str:
        """Get a fresh captcha token.

        Opens a dedicated tab, runs the captcha flow, closes the tab.
        The browser context (cookies, storage) persists across calls.
        """
        if not self._context:
            raise RuntimeError("Session not started. Call start() first.")

        print(f"[*] Getting fresh captcha token (new tab)...", file=sys.stderr)

        page = self._context.new_page()
        try:
            page.goto("https://chat.z.ai/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("#chat-input", timeout=15000)
            time.sleep(1)

            certify_id, security_token = _trigger_captcha_flow(page)
        finally:
            page.close()

        raw, param_obj = _build_captcha_raw(certify_id, security_token)

        if save:
            CACHE_FILE.write_text(
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

    def close(self):
        """Clean up browser resources."""
        if self._browser_ctx:
            try:
                self._browser_ctx.__exit__(None, None, None)
            except Exception:
                pass
            self._browser_ctx = None
            self._browser = None
            self._context = None

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
