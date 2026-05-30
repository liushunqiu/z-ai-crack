#!/usr/bin/env python3
"""
Z.ai API Client v2 - Full featured
Handles: login, captcha, signature, streaming chat

Architecture:
  1. First call: opens browser for captcha + signature capture
  2. Subsequent calls: reuses session (captcha may not be needed every time)

Usage:
  from zaibot_client import ZaibotClient
  client = ZaibotClient()
  reply = client.ask("hello")
"""
import json
import time
import uuid
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional, Generator

from zaibot_core import get_fe_version

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "zaibot_state.json"
TOKEN_FILE = BASE_DIR / "zaibot_token.txt"
CAPTCHA_FILE = BASE_DIR / "zaibot_captcha.json"

API_BASE = "https://chat.z.ai/api"


def _get_user_id(token: str) -> str:
    """Extract user_id from JWT token."""
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            import base64
            payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload))
            return data.get("id", "")
    except Exception:
        pass
    return ""


def _generate_request_id() -> str:
    return str(uuid.uuid4())


def _build_url_params(timestamp: str, request_id: str, user_id: str, token: str) -> str:
    """Build the URL query parameters matching the frontend's rV() output."""
    params = {
        "timestamp": timestamp,
        "requestId": request_id,
        "user_id": user_id,
        "version": "0.0.1",
        "platform": "web",
        "token": token,
        # Browser fingerprint (static values work for API calls)
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
        "language": "en-US",
        "languages": "en-US,en",
        "timezone": "Asia/Shanghai",
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
        "browser_name": "Firefox",
        "os_name": "Mac OS",
        "signature_timestamp": timestamp,
    }
    return urllib.parse.urlencode(params)


def _build_sorted_payload(timestamp: str, request_id: str, user_id: str) -> str:
    """Build the sorted payload string for signature (keys sorted alphabetically)."""
    o = {
        "requestId": request_id,
        "timestamp": timestamp,
        "user_id": user_id,
    }
    sorted_keys = sorted(o.keys())
    return ",".join(f"{k}:{o[k]}" for k in sorted_keys)


class ZaibotClient:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.token: Optional[str] = None
        self.user_id: Optional[str] = None
        self._load_token()

    def _load_token(self):
        if TOKEN_FILE.exists():
            self.token = TOKEN_FILE.read_text().strip()
            self.user_id = _get_user_id(self.token)

    def _get_signature_via_browser(self, sorted_payload: str, prompt: str, timestamp: str) -> str:
        """Use Camoufox browser to compute the HMAC-SHA256 signature."""
        try:
            from camoufox import Camoufox, DefaultAddons
        except ImportError:
            raise RuntimeError("camoufox not installed. Use: pip install camoufox")

        state = None
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                state = json.load(f)

        signature_result = {"signature": None, "timestamp": None, "captcha_param": None}

        with Camoufox(
            headless=self.headless,
            geoip=False,
            humanize=True,
            exclude_addons=[DefaultAddons.UBO],
            firefox_user_prefs={
                "privacy.trackingprotection.enabled": False,
                "privacy.trackingprotection.pbmode.enabled": False,
                "privacy.trackingprotection.fingerprinting.enabled": False,
                "privacy.trackingprotection.cryptomining.enabled": False,
            },
        ) as browser:
            ctx_kwargs = {}
            if state:
                ctx_kwargs["storage_state"] = state
            context = browser.new_context(**ctx_kwargs)

            # Install fetch interceptor to capture signature
            context.add_init_script("""
                const origFetch = window.fetch;
                window.__sigCapture = [];
                window.fetch = function(...args) {
                    const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
                    if (url.includes('chat/completions')) {
                        const req = args[1] || {};
                        let headers = {};
                        if (req.headers) {
                            if (req.headers instanceof Headers) {
                                req.headers.forEach((v, k) => headers[k] = v);
                            } else {
                                headers = {...req.headers};
                            }
                        }
                        // Extract signature from URL
                        const urlObj = new URL(url);
                        window.__sigCapture.push({
                            signature: headers['x-signature'] || headers['X-Signature'] || '',
                            timestamp: urlObj.searchParams.get('signature_timestamp') || '',
                            urlParams: urlObj.search.substring(1),
                        });
                    }
                    return origFetch.apply(this, args);
                };
            """)

            page = context.new_page()
            page.goto("https://chat.z.ai/", wait_until="domcontentloaded")
            time.sleep(3)

            # Type and send message
            page.evaluate("""(prompt) => {
                const textarea = document.querySelector('#chat-input');
                if (!textarea) throw new Error('chat-input not found');
                textarea.focus();
                const nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeSetter.call(textarea, prompt);
                textarea.dispatchEvent(new InputEvent('input', {
                    bubbles: true, cancelable: true,
                    inputType: 'insertText', data: prompt
                }));
            }""", prompt)
            time.sleep(0.5)

            # Click send
            send_btn = page.query_selector("#send-message-button")
            if send_btn and not send_btn.is_disabled():
                send_btn.click()
                print("[*] Message sent, waiting for signature capture...")
            else:
                print("[!] Send button disabled - waiting for captcha...")
                # Wait for user to solve captcha
                for _ in range(120):
                    time.sleep(2)
                    send_btn = page.query_selector("#send-message-button")
                    if send_btn and not send_btn.is_disabled():
                        page.evaluate("""(prompt) => {
                            const textarea = document.querySelector('#chat-input');
                            const nativeSetter = Object.getOwnPropertyDescriptor(
                                window.HTMLTextAreaElement.prototype, 'value'
                            ).set;
                            nativeSetter.call(textarea, prompt);
                            textarea.dispatchEvent(new InputEvent('input', {
                                bubbles: true, cancelable: true,
                                inputType: 'insertText', data: prompt
                            }));
                        }""", prompt)
                        time.sleep(0.3)
                        send_btn.click()
                        print("[*] Message sent after captcha")
                        break

            # Wait for signature capture
            for _ in range(60):
                time.sleep(1)
                captures = page.evaluate("window.__sigCapture || []")
                if captures and len(captures) > 0:
                    sig = captures[0]
                    signature_result["signature"] = sig.get("signature", "")
                    signature_result["timestamp"] = sig.get("timestamp", "")
                    print(f"[+] Signature captured: {sig['signature'][:32]}...")
                    break

            # Save updated state
            new_state = context.storage_state()
            with open(STATE_FILE, "w") as f:
                json.dump(new_state, f, indent=2)

        return signature_result.get("signature", "")

    def ask(self, prompt: str, model: str = "GLM-5.1", stream: bool = False) -> str:
        """Send a chat message and get response."""
        if not self.token:
            raise RuntimeError("Not logged in. Run: python3 login.py login")

        timestamp = str(int(time.time() * 1000))
        request_id = _generate_request_id()

        # Build signature (uses browser to compute HMAC)
        sorted_payload = _build_sorted_payload(timestamp, request_id, self.user_id)
        signature = self._get_signature_via_browser(sorted_payload, prompt, timestamp)

        if not signature:
            raise RuntimeError("Failed to capture signature")

        # Build URL
        url_params = _build_url_params(timestamp, request_id, self.user_id, self.token)
        url = f"{API_BASE}/v2/chat/completions?{url_params}"

        # Build body
        body = {
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
                "enable_thinking": False,
            },
            "variables": {
                "{{USER_NAME}}": "",
                "{{USER_LOCATION}}": "Unknown",
                "{{CURRENT_DATETIME}}": time.strftime("%Y-%m-%d %H:%M:%S"),
                "{{CURRENT_DATE}}": time.strftime("%Y-%m-%d"),
                "{{CURRENT_TIME}}": time.strftime("%H:%M:%S"),
                "{{CURRENT_WEEKDAY}}": time.strftime("%A"),
                "{{CURRENT_TIMEZONE}}": "Asia/Shanghai",
                "{{USER_LANGUAGE}}": "en-US",
            },
            "chat_id": str(uuid.uuid4()),
            "id": str(uuid.uuid4()),
            "background_tasks": {"title_generation": True, "tags_generation": True},
        }

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept-Language": "en-US",
            "X-FE-Version": get_fe_version(),
            "X-Region": "overseas",
            "X-Signature": signature,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            if stream:
                return self._parse_stream(resp)
            else:
                data = json.loads(resp.read())
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    def _parse_stream(self, resp) -> str:
        """Parse SSE stream response."""
        result = []
        for line in resp:
            line = line.decode("utf-8", errors="replace").strip()
            if not line or line == "data: [DONE]":
                continue
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    content = data.get("data", {}).get("delta_content", "")
                    phase = data.get("data", {}).get("phase", "")
                    if phase == "answer" and content:
                        result.append(content)
                        print(content, end="", flush=True)
                except json.JSONDecodeError:
                    continue
        print()
        return "".join(result)


if __name__ == "__main__":
    import sys
    prompt = " ".join(sys.argv[1:]) or "hello, say hi in 5 words"
    client = ZaibotClient(headless=False)
    reply = client.ask(prompt)
    print(f"\n=== Reply ===\n{reply}")
