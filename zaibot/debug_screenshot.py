#!/usr/bin/env python3
"""Z.ai Chat - Screenshot-based captcha debug"""
import json, time
from pathlib import Path
from camoufox import Camoufox

STATE_FILE = Path(__file__).parent / "zaibot_state.json"

with open(STATE_FILE) as f:
    state = json.load(f)

with Camoufox(headless=False, geoip=False, humanize=True) as browser:
    context = browser.new_context(storage_state=state)
    page = context.new_page()
    page.set_default_timeout(60000)
    page.goto("https://chat.z.ai/", wait_until="domcontentloaded")
    time.sleep(3)
    page.screenshot(path="/tmp/zaibot_1_loaded.png")
    print("[1] Page loaded, screenshot saved")

    # Load captcha SDK
    page.evaluate("""
    (async () => {
        window.AliyunCaptchaConfig = { region: 'sgp', prefix: 'no8xfe' };
        const resp = await fetch('https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js');
        eval(await resp.text());
        return typeof window.initAliyunCaptcha;
    })()
    """)
    time.sleep(2)

    has_init = page.evaluate("typeof window.initAliyunCaptcha")
    print(f"[2] initAliyunCaptcha = {has_init}")

    if has_init == "function":
        page.screenshot(path="/tmp/zaibot_2_sdk.png")

        page.evaluate("""
        (() => {
            for (const id of ['chat-captcha-element', 'chat-captcha-trigger']) {
                if (!document.getElementById(id)) {
                    const el = document.createElement('div');
                    el.id = id;
                    el.style.cssText = 'position:absolute;left:-99999px;width:1px;height:1px;';
                    document.body.appendChild(el);
                }
            }
        })()
        """)

        page.evaluate("""
        (() => {
            window.initAliyunCaptcha({
                SceneId: 'didk33e0', mode: 'popup',
                element: '#chat-captcha-element',
                button: '#chat-captcha-trigger',
                language: 'en', timeout: 10000,
                delayBeforeSuccess: false,
                success: d => console.log('OK', typeof d),
                fail: e => console.log('FAIL', String(e)),
                onError: e => console.log('ERR', String(e)),
            });
        })()
        """)
        time.sleep(3)
        page.screenshot(path="/tmp/zaibot_3_init.png")
        print("[3] initAliyunCaptcha called, screenshot saved")

        page.click("#chat-captcha-trigger")
        time.sleep(3)
        page.screenshot(path="/tmp/zaibot_4_clicked.png")
        print("[4] Trigger clicked, screenshot saved")

    input("Press Enter to close...")
