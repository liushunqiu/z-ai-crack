#!/usr/bin/env python3
"""Quick test: can real Chrome (playwright chromium) get a certId + send chat completion
without hitting Aliyun WAF 405?

If this script returns a 200 from /api/v2/chat/completions, the issue is Camoufox
fingerprint and we can refactor captcha_service.py to use Chrome instead.

Usage:
  python3 test_chrome_works.py <path-to-state.json>
"""
import json
import os
import random
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL_CHAT = "https://chat.z.ai/"
URL_COMPLETIONS = "https://chat.z.ai/api/v2/chat/completions"

if len(sys.argv) < 2:
    print("Usage: python3 test_chrome_works.py <path-to-state.json>")
    sys.exit(1)

state_path = Path(sys.argv[1])
state = json.loads(state_path.read_text())
print(f"[*] Loaded state from {state_path}")

# Pick screen-size variant to look more like a real user
sizes = [(1280, 800), (1366, 768), (1440, 900), (1920, 1080)]
vw, vh = random.choice(sizes)

with sync_playwright() as p:
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
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
        viewport={"width": vw, "height": vh},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        locale="en-US",
        timezone_id="America/Los_Angeles",
    )

    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    """)

    page = context.new_page()

    captured_captcha = {"certifyId": None, "securityToken": None, "init": False}
    waf_block = {"status": None, "body": None}
    all_responses = []

    def on_response(resp):
        url = resp.url
        all_responses.append({"url": url[:80], "method": resp.request.method, "status": resp.status})
        if "captcha-open" in url and resp.request.method == "POST":
            captured_captcha["init"] = True
            try:
                body = resp.json()
                if isinstance(body, dict):
                    result = body.get("Result", {})
                    if result.get("securityToken"):
                        captured_captcha["certifyId"] = result.get("certifyId")
                        captured_captcha["securityToken"] = result["securityToken"]
                        print(f"[OK] Got securityToken! certId={captured_captcha['certifyId']}")
            except Exception as e:
                print(f"[!] captcha response parse error: {e}")
        if "/api/v2/chat/completions" in url and resp.request.method == "POST":
            waf_block["status"] = resp.status
            if resp.status >= 400:
                try:
                    waf_block["body"] = resp.text()[:300]
                except Exception:
                    waf_block["body"] = "<no body>"
                print(f"[!] completion status={resp.status}: {waf_block['body'][:200]}")

    page.on("response", on_response)

    print(f"[*] Loading {URL_CHAT} (viewport {vw}x{vh}) ...")
    page.goto(URL_CHAT, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("#chat-input", timeout=15000)
    print(f"[*] Page loaded. Title: {page.title()}")

    screenshot_loaded = "/tmp/chrome_loaded.png"
    page.screenshot(path=screenshot_loaded, full_page=True)
    print(f"[*] Screenshot of loaded page: {screenshot_loaded}")

    btn_state = page.evaluate("""() => {
        const btn = document.getElementById('send-message-button');
        if (!btn) return {found: false};
        const r = btn.getBoundingClientRect();
        return {
            found: true,
            disabled: btn.disabled,
            visible: r.width > 0 && r.height > 0,
            x: Math.round(r.left + r.width / 2),
            y: Math.round(r.top + r.height / 2),
            w: r.width, h: r.height,
        };
    }""")
    print(f"[*] send button: {btn_state}")

    overlay = page.evaluate("""() => {
        const overlays = [];
        for (const sel of ['[role="dialog"]', '.modal', '.captcha', 'iframe', '[class*="Captcha"]', '[class*="captcha"]', '[id*="captcha"]']) {
            try {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        overlays.push({tag: el.tagName, cls: (el.className||'').toString().slice(0,40), id: el.id||'', x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)});
                    }
                }
            } catch(e) {}
        }
        return overlays;
    }""")
    if overlay:
        print(f"[*] Overlays/dialogs/iframes on page:")
        for o in overlay:
            print(f"    {o}")
    else:
        print("[*] No overlays/dialogs detected")

    time.sleep(random.uniform(0.5, 1.2))
    page.locator("#chat-input").click()
    time.sleep(random.uniform(0.2, 0.4))
    page.keyboard.type("hi", delay=random.uniform(60, 160))
    time.sleep(random.uniform(1.0, 2.5))

    # Click send
    if not btn_state.get("found") or btn_state.get("disabled"):
        print(f"[!] send button unavailable; trying JS click")
        page.evaluate("""() => {
            const btn = document.getElementById('send-message-button');
            if (btn && !btn.disabled) btn.click();
        }""")
    else:
        tx = btn_state["x"]
        ty = btn_state["y"]
        sx = random.uniform(100, max(200, vw - 200))
        sy = random.uniform(100, max(200, vh - 200))
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
        print(f"[*] Clicked send at ({tx}, {ty})")

    # Screenshot after click to see if a captcha widget appeared
    time.sleep(2.5)
    screenshot_after = "/tmp/chrome_after_click.png"
    page.screenshot(path=screenshot_after, full_page=True)
    print(f"[*] Screenshot 2.5s after click: {screenshot_after}")

    # Wait up to 30s for securityToken or completion
    for i in range(60):
        time.sleep(0.5)
        if captured_captcha["securityToken"] or waf_block["status"]:
            break

    print()
    print("=" * 60)
    print(f"RESULT:")
    print(f"  securityToken:  {captured_captcha['securityToken'] or 'NOT OBTAINED'}")
    print(f"  InitCaptcha fired: {captured_captcha['init']}")
    print(f"  completion status: {waf_block['status']}")
    print(f"  completion body: {(waf_block['body'] or '')[:200]}")
    print()
    print(f"  All observed responses ({len(all_responses)}):")
    for r in all_responses[:15]:
        print(f"    {r['method']:6s} {r['status']:3d}  {r['url']}")
    if len(all_responses) > 15:
        print(f"    ... and {len(all_responses) - 15} more")
    print("=" * 60)

    if captured_captcha["securityToken"] and waf_block["status"] == 200:
        print("[VERDICT] Chrome works! The issue is Camoufox. Switch to Chrome.")
    elif captured_captcha["securityToken"] and waf_block["status"] and waf_block["status"] >= 400:
        print(f"[VERDICT] Chrome gets certId but WAF returns {waf_block['status']}. Deeper issue.")
    elif not captured_captcha["init"]:
        print("[VERDICT] Chrome click does not even trigger InitCaptcha. UI/button problem or Aliyun silently blocks Chrome too.")
    else:
        print("[VERDICT] Captcha triggered but no securityToken in 30s. Aliyun may be showing a challenge widget for Chrome.")

    browser.close()
