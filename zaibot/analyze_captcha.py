#!/usr/bin/env python3
"""
Analyze the Aliyun captcha SDK flow by intercepting network requests.
Uses Camoufox to handle the captcha naturally, then captures all traffic.
"""
import json
import time
from pathlib import Path
from camoufox import Camoufox, DefaultAddons

STATE_FILE = Path(__file__).parent / "zaibot_state.json"
OUTPUT_FILE = Path(__file__).parent / "captcha_analysis.json"


def analyze():
    with open(STATE_FILE) as f:
        state = json.load(f)

    captured = {"requests": [], "captcha_flows": []}

    with Camoufox(
        headless=False,
        geoip=False,
        humanize=True,
        exclude_addons=[DefaultAddons.UBO],
        firefox_user_prefs={
            "privacy.trackingprotection.enabled": False,
            "privacy.trackingprotection.pbmode.enabled": False,
        },
    ) as browser:
        context = browser.new_context(storage_state=state)
        page = context.new_page()

        # Capture ALL network requests
        def handle_request(request):
            url = request.url
            # Filter for captcha-related and API requests
            keywords = ['captcha', 'verify', 'check', 'certify', 'saf.', 'cloudauth',
                       'device', 'aliyuncs', 'chat/completions']
            if any(kw in url.lower() for kw in keywords):
                data = {
                    "url": url,
                    "method": request.method,
                    "headers": dict(request.headers),
                    "body": request.post_data,
                    "timestamp": time.time(),
                }
                captured["requests"].append(data)
                print(f"[REQ] {request.method} {url[:120]}")
                if request.post_data:
                    print(f"  Body: {request.post_data[:200]}")

        def handle_response(response):
            url = response.url
            keywords = ['captcha', 'verify', 'check', 'certify', 'saf.', 'cloudauth',
                       'device', 'aliyuncs', 'chat/completions']
            if any(kw in url.lower() for kw in keywords):
                try:
                    body = response.text()
                except:
                    body = "<binary>"
                data = {
                    "url": url,
                    "status": response.status,
                    "body": body[:2000] if body else None,
                    "timestamp": time.time(),
                }
                captured["requests"].append({"response": data})
                print(f"[RESP] {response.status} {url[:120]}")
                if body and len(body) < 500:
                    print(f"  Body: {body[:200]}")

        page.on("request", handle_request)
        page.on("response", handle_response)

        # Also hook the captcha success callback
        page.add_init_script("""
        (function() {
            // Hook btoa to capture captcha verify param
            const origBtoa = window.btoa;
            window.__captchaVerifyParams = [];
            window.btoa = function(s) {
                const result = origBtoa.call(this, s);
                if (typeof s === 'string' && s.includes('certifyId')) {
                    window.__captchaVerifyParams.push({raw: s, encoded: result});
                    console.log('[CAPTCHA_PARAM]', result);
                }
                return result;
            };

            // Hook the captcha success callback
            // The frontend calls nre(e) on success
            // We intercept by hooking Promise.resolve
            window.__captchaSuccess = [];
            const origThen = Promise.prototype.then;
            Promise.prototype.then = function(onFulfilled, onRejected) {
                const wrappedOnFulfilled = onFulfilled ? function(value) {
                    if (typeof value === 'string' && value.length > 100 && value.includes('=')) {
                        window.__captchaSuccess.push(value);
                        console.log('[CAPTCHA_SUCCESS]', value.substring(0, 100));
                    }
                    return onFulfilled.call(this, value);
                } : onFulfilled;
                return origThen.call(this, wrappedOnFulfilled, onRejected);
            };
        })();
        """)

        page.goto("https://chat.z.ai/", wait_until="domcontentloaded")
        time.sleep(3)

        # Type and send message
        page.evaluate("""() => {
            const textarea = document.querySelector('#chat-input');
            textarea.focus();
            const nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            nativeSetter.call(textarea, 'test captcha analysis');
            textarea.dispatchEvent(new InputEvent('input', {
                bubbles: true, cancelable: true,
                inputType: 'insertText', data: 'test captcha analysis'
            }));
        }""")
        time.sleep(0.5)

        send_btn = page.query_selector("#send-message-button")
        if send_btn and not send_btn.is_disabled():
            send_btn.click()
            print("[*] Message sent, waiting for captcha...")

        print("=" * 60)
        print("  Please solve the captcha in the browser")
        print("  The script will capture all network traffic")
        print("=" * 60)

        # Wait for captcha to be solved and request to complete
        for i in range(180):
            time.sleep(2)

            # Check if request was sent
            chat_reqs = [r for r in captured["requests"]
                        if isinstance(r, dict) and "chat/completions" in r.get("url", "")]
            if chat_reqs:
                print(f"\n[+] Chat request captured at {i*2}s!")
                break

            if i % 15 == 0:
                print(f"  [{i*2}s] waiting...")

        # Get captcha verify params from page context
        verify_params = page.evaluate("window.__captchaVerifyParams || []")
        captcha_success = page.evaluate("window.__captchaSuccess || []")

        captured["verify_params"] = verify_params
        captured["captcha_success"] = captcha_success

        # Save results
        with open(OUTPUT_FILE, "w") as f:
            json.dump(captured, f, indent=2, ensure_ascii=False)
        print(f"\n[+] Analysis saved to {OUTPUT_FILE}")
        print(f"  Total requests captured: {len(captured['requests'])}")
        print(f"  Verify params: {len(verify_params)}")
        print(f"  Captcha success: {len(captcha_success)}")


if __name__ == "__main__":
    analyze()
