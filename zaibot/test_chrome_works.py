#!/usr/bin/env python3
"""Quick test: can real Chrome (playwright chromium) get a certId + send chat completion
without hitting Aliyun WAF 405?

If this script returns a 200 from /api/v2/chat/completions, the issue is Camoufox
fingerprint and we can refactor captcha_service.py to use Chrome instead.

Usage:
  python3 test_chrome_works.py /path/to/state.json
"""
import json
import sys
import time
import random
from pathlib import Path

from playwright.sync_api import sync_playwright

URL_CHAT = "https://chat.z.ai/"
URL_CAPTCHA_INIT = "https://captcha-open-southeast.aliyuncs.com/..."  # not needed, we observe network
URL_COMPLETIONS = "https://chat.z.ai/api/v2/chat/completions"

if len(sys.argv) < 2:
    print("Usage: python3 test_chrome_works.py <path-to-state.json>")
    sys.exit(1)

state_path = Path(sys.argv[1])
state = json.loads(state_path.read_text())
print(f"[*] Loaded state from {state_path}")

with sync_playwright() as p:
    # Try system Google Chrome first (faster, no need to install browser bundle).
    # Fall back to bundled chromium if Chrome is missing.
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    import os
    use_system_chrome = os.path.exists(chrome_path)
    if use_system_chrome:
        print(f"[*] Using system Chrome: {chrome_path}")
        browser = p.chromium.launch(
            headless=True,
            executable_path=chrome_path,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
    else:
        print("[*] No system Chrome, using bundled chromium")
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
    context = browser.new_context(
        storage_state=state,
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        locale="en-US",
        timezone_id="America/Los_Angeles",
    )

    # Anti-detect: override navigator.webdriver
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
    """)

    page = context.new_page()

    captured_captcha = {"certifyId": None, "securityToken": None}
    waf_block = {"status": None, "body": None}

    def on_response(resp):
        url = resp.url
        if "captcha-open" in url and resp.request.method == "POST":
            try:
                body = resp.json()
                if isinstance(body, dict):
                    result = body.get("Result", {})
                    if result.get("securityToken"):
                        captured_captcha["certifyId"] = result.get("certifyId")
                        captured_captcha["securityToken"] = result["securityToken"]
                        print(f"[✓] Got certId={captured_captcha['certifyId']}")
            except Exception:
                pass
        if "/api/v2/chat/completions" in url and resp.request.method == "POST":
            waf_block["status"] = resp.status
            if resp.status >= 400:
                try:
                    waf_block["body"] = resp.text()[:300]
                except Exception:
                    waf_block["body"] = "<no body>"
                print(f"[!] completion status={resp.status}: {waf_block['body'][:200]}")

    page.on("response", on_response)

    print(f"[*] Loading {URL_CHAT} ...")
    page.goto(URL_CHAT, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("#chat-input", timeout=15000)
    print(f"[*] Page loaded. Title: {page.title()}")

    # Real-ish typing
    time.sleep(random.uniform(0.5, 1.2))
    page.locator("#chat-input").click()
    time.sleep(random.uniform(0.2, 0.4))
    page.keyboard.type("hi", delay=random.uniform(60, 160))
    time.sleep(random.uniform(1.0, 2.5))

    # Click send
    btn = page.locator("#send-message-button")
    box = btn.bounding_box()
    if not box:
        print("[!] send button has no bounding box")
    else:
        tx = box["x"] + box["width"] / 2
        ty = box["y"] + box["height"] / 2
        sx = random.uniform(100, 600)
        sy = random.uniform(100, 400)
        for step in range(1, 5):
            t = step / 4
            jit = 1 - abs(t - 0.5) * 2
            page.mouse.move(
                sx + (tx - sx) * t + random.uniform(-12, 12) * jit,
                sy + (ty - sy) * t + random.uniform(-12, 12) * jit,
                steps=4,
            )
            time.sleep(random.uniform(0.02, 0.06))
        time.sleep(random.uniform(0.05, 0.15))
        page.mouse.click(tx, ty)
        print(f"[*] Clicked send button at ({tx:.0f}, {ty:.0f})")

    # Wait for captcha + completion
    for i in range(40):
        time.sleep(0.5)
        if captured_captcha["securityToken"]:
            break

    if not captured_captcha["securityToken"]:
        print("[!] Did NOT get securityToken in 20s. Aliyun captcha is also blocking Chrome.")
        print(f"    WAF block status so far: {waf_block['status']}")
    else:
        print(f"[✓] Captcha OK with Chrome. certifyId={captured_captcha['certifyId']}")
        print(f"    Completion status: {waf_block['status']}")
        if waf_block["status"] == 200:
            print("[✓] Chrome works! Camoufox is the problem. We should switch.")
        elif waf_block["status"] and waf_block["status"] >= 400:
            print(f"[!] Even Chrome gets {waf_block['status']} from WAF. Deeper problem.")
        else:
            print("[?] Completion didn't fire. Check if /api/v2/chat/completions was actually called.")

    browser.close()
