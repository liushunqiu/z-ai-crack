#!/usr/bin/env python3
"""Get captcha_verify_param automatically from real Chrome AliyunCaptcha SDK.

No manual slider if Aliyun returns VerifyCaptchaV3 success automatically.
Falls back to the visible popup if Aliyun requires interaction.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent
CACHE_FILE = BASE_DIR / "zaibot_captcha_cache.json"
STATE_FILE = BASE_DIR / "zaibot_state.json"
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
]


def find_chrome():
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return None


def launch_chrome(port: int):
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Chrome not found")
    user_data_dir = Path.home() / ".config" / f"zaibot-chrome-captcha-{port}"
    return subprocess.Popen([
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_cdp(port: int):
    for _ in range(30):
        time.sleep(1)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).read()
            return
        except Exception:
            pass
    raise RuntimeError(f"CDP port {port} not reachable")


def get_auto_captcha(port: int | None = None, save: bool = True, timeout: int = 150) -> str:
    port = port or int(os.environ.get("ZAIBOT_CDP_PORT", "9340"))
    launch_chrome(port)
    wait_cdp(port)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=15000)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        # Rehydrate login state saved by login.py. New Chrome profiles do not
        # share Camoufox/Playwright storage automatically.
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
                cookies = state.get("cookies") or []
                if cookies:
                    ctx.add_cookies(cookies)
            except Exception:
                pass
        page = ctx.new_page()
        page.goto("https://chat.z.ai/", wait_until="domcontentloaded", timeout=60000)
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
                origins = state.get("origins") or []
                for origin in origins:
                    if origin.get("origin") == "https://chat.z.ai":
                        for item in origin.get("localStorage", []):
                            page.evaluate("([k,v]) => localStorage.setItem(k,v)", [item.get("name"), item.get("value")])
                        page.reload(wait_until="domcontentloaded", timeout=60000)
                        break
            except Exception:
                pass
        # Do not require body to be visible; auth redirects can leave it hidden
        # while localStorage is being rehydrated.
        time.sleep(2)
        page.evaluate(r"""
        async () => {
          window.__captchaResults = [];
          window.__captchaErrors = [];
          for (const id of ['chat-captcha-element', 'chat-captcha-trigger']) {
            if (!document.getElementById(id)) {
              const el = document.createElement(id === 'chat-captcha-trigger' ? 'button' : 'div');
              el.id = id; document.body.appendChild(el);
            }
          }
          window.AliyunCaptchaConfig = {region: 'sgp', prefix: 'no8xfe'};
          if (typeof initAliyunCaptcha !== 'function') {
            await new Promise((resolve, reject) => {
              const s = document.createElement('script');
              s.src = 'https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js';
              s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
            });
          }
          initAliyunCaptcha({
            SceneId: 'didk33e0', mode: 'popup', element: '#chat-captcha-element', button: '#chat-captcha-trigger',
            language: 'en', timeout: 120000, delayBeforeSuccess: false,
            success: (p) => { window.__captchaResults.push(p); console.log('[CAPTCHA_OK]', p); },
            fail: (e) => { window.__captchaErrors.push(e); console.log('[CAPTCHA_FAIL]', JSON.stringify(e)); },
            onError: (e) => { window.__captchaErrors.push(e); console.log('[CAPTCHA_ERR]', JSON.stringify(e)); },
            getInstance: (inst) => { window.__captchaInstance = inst; console.log('[CAPTCHA_INST]'); },
          });
        }
        """)
        # Give FeiLin and dynamicJS time to initialize before clicking trigger.
        time.sleep(8)
        page.evaluate("document.getElementById('chat-captcha-trigger').click()")
        for _ in range(timeout):
            time.sleep(1)
            results = page.evaluate("window.__captchaResults || []")
            if results:
                raw = results[0]
                decoded = json.loads(base64.b64decode(raw))
                if save:
                    CACHE_FILE.write_text(json.dumps({
                        "raw": raw,
                        "decoded": decoded,
                        "timestamp": time.time(),
                        "source": "auto_captcha.py",
                    }, indent=2, ensure_ascii=False), encoding="utf-8")
                browser.close()
                return raw
        errors = page.evaluate("window.__captchaErrors || []")
        browser.close()
        raise RuntimeError(f"captcha timeout/errors: {errors}")


if __name__ == "__main__":
    raw = get_auto_captcha()
    print(raw)
