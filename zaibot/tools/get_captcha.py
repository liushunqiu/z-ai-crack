#!/usr/bin/env python3
"""
Get captcha_verify_param from your real Chrome browser.
Chrome's fingerprint passes FeiLin SDK detection.

Usage:
  1. Run this script
  2. It will open Chrome to chat.z.ai
  3. Solve the captcha (slide puzzle)
  4. The verify param is saved to zaibot_captcha_cache.json

Requires: Google Chrome installed at default location.
"""
import json
import sys
import time
import base64
import subprocess
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
CACHE_FILE = BASE_DIR / "zaibot_captcha_cache.json"

# Chrome paths
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


def get_captcha():
    chrome_path = find_chrome()
    if not chrome_path:
        print("[x] Chrome not found. Install Google Chrome.", file=sys.stderr)
        sys.exit(1)

    # Launch Chrome with remote debugging
    debug_port = 9222
    user_data_dir = Path.home() / ".config" / "zaibot-chrome-profile"

    print(f"[*] Launching Chrome on port {debug_port}...", file=sys.stderr)
    proc = subprocess.Popen([
        chrome_path,
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://chat.z.ai/",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    time.sleep(3)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[x] playwright not installed", file=sys.stderr)
        proc.terminate()
        sys.exit(1)

    with sync_playwright() as p:
        # Connect to the running Chrome
        print(f"[*] Connecting to Chrome on port {debug_port}...", file=sys.stderr)
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
        except Exception as e:
            print(f"[x] Failed to connect: {e}", file=sys.stderr)
            print("[*] Make sure Chrome is running with --remote-debugging-port=9222", file=sys.stderr)
            proc.terminate()
            sys.exit(1)

        contexts = browser.contexts
        if not contexts:
            print("[x] No browser context found", file=sys.stderr)
            browser.close()
            proc.terminate()
            sys.exit(1)

        context = contexts[0]
        pages = context.pages

        # Find the chat.z.ai page
        page = None
        for pg in pages:
            if "chat.z.ai" in pg.url:
                page = pg
                break

        if not page:
            page = context.new_page()
            page.goto("https://chat.z.ai/", wait_until="domcontentloaded")

        page.wait_for_selector("#chat-input", timeout=30000)
        time.sleep(3)

        print("[*] Page loaded. Setting up captcha capture...", file=sys.stderr)

        # Inject captcha capture
        page.evaluate("""() => {
            window.__captchaResults = [];
            window.__captchaErrors = [];

            // Check if captcha SDK is already loaded
            if (typeof initAliyunCaptcha === 'function') {
                // Create elements if needed
                for (const id of ['chat-captcha-element', 'chat-captcha-trigger']) {
                    if (!document.getElementById(id)) {
                        const el = document.createElement('div');
                        el.id = id;
                        document.body.appendChild(el);
                    }
                }

                initAliyunCaptcha({
                    SceneId: 'didk33e0', mode: 'popup',
                    element: '#chat-captcha-element', button: '#chat-captcha-trigger',
                    language: 'en', timeout: 120000, delayBeforeSuccess: false,
                    success: (p) => {
                        window.__captchaResults.push(p);
                        console.log('[CAPTCHA_OK]', p.substring(0, 100));
                    },
                    fail: (e) => {
                        window.__captchaErrors.push(e);
                        console.log('[CAPTCHA_FAIL]', JSON.stringify(e));
                    },
                    onError: (e) => {
                        window.__captchaErrors.push(e);
                        console.log('[CAPTCHA_ERR]', JSON.stringify(e));
                    },
                    getInstance: (inst) => {
                        window.__captchaInstance = inst;
                        console.log('[CAPTCHA_INST]');
                    },
                });
            }
        }""")

        time.sleep(15)

        has_instance = page.evaluate("!!window.__captchaInstance")
        errors = page.evaluate("window.__captchaErrors || []")

        if not has_instance:
            print(f"[!] Captcha instance not created. Errors: {json.dumps(errors)}", file=sys.stderr)
            # Try triggering via message send first
            page.evaluate("""() => {
                const t = document.querySelector('#chat-input');
                t.focus();
                Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(t,'init');
                t.dispatchEvent(new Event('input', {bubbles: true}));
            }""")
            time.sleep(0.5)
            send_btn = page.query_selector("#send-message-button")
            if send_btn and not send_btn.is_disabled():
                send_btn.click()
            time.sleep(15)

            # Re-init
            page.evaluate("""() => {
                window.__captchaResults = [];
                window.__captchaErrors = [];
                if (typeof initAliyunCaptcha === 'function') {
                    for (const id of ['chat-captcha-element', 'chat-captcha-trigger']) {
                        if (!document.getElementById(id)) {
                            const el = document.createElement('div'); el.id = id;
                            document.body.appendChild(el);
                        }
                    }
                    initAliyunCaptcha({
                        SceneId: 'didk33e0', mode: 'popup',
                        element: '#chat-captcha-element', button: '#chat-captcha-trigger',
                        language: 'en', timeout: 120000, delayBeforeSuccess: false,
                        success: (p) => { window.__captchaResults.push(p); },
                        fail: (e) => { window.__captchaErrors.push(e); },
                        onError: (e) => { window.__captchaErrors.push(e); },
                        getInstance: (inst) => { window.__captchaInstance = inst; },
                    });
                }
            }""")
            time.sleep(15)

        # Trigger captcha
        page.evaluate('document.getElementById("chat-captcha-trigger").click()')
        print("[*] Captcha triggered! Please solve the slide puzzle in Chrome.", file=sys.stderr)
        print("[*] Waiting up to 120 seconds...", file=sys.stderr)

        for i in range(120):
            time.sleep(2)
            results = page.evaluate("window.__captchaResults || []")
            if results:
                raw = results[0]
                decoded = json.loads(base64.b64decode(raw))
                has_token = "securityToken" in decoded
                print(f"\n[+] Captcha solved! hasSecurityToken={has_token}", file=sys.stderr)
                print(f"    Keys: {list(decoded.keys())}", file=sys.stderr)

                cache = {"raw": raw, "decoded": decoded, "timestamp": time.time()}
                with open(CACHE_FILE, "w") as f:
                    json.dump(cache, f, indent=2)
                print(f"[+] Saved to {CACHE_FILE}", file=sys.stderr)

                # Don't close Chrome - user might want to keep using it
                browser.close()
                return raw

            if i % 15 == 0:
                print(f"  [{i*2}s] waiting...", file=sys.stderr)

        print("[x] Captcha timeout", file=sys.stderr)
        browser.close()
        return ""


if __name__ == "__main__":
    result = get_captcha()
    if result:
        print(result)
