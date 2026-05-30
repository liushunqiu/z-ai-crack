#!/usr/bin/env python3
"""
Z.ai Signature Server - persistent browser session for signature generation.
Keeps a Camoufox browser running and generates signatures via stdin/stdout.

Usage:
  python3 signature_server.py

Then send JSON commands via stdin:
  {"cmd": "sign", "prompt": "hello", "timestamp": "1779956218691"}
  {"cmd": "captcha_param"}
  {"cmd": "status"}
  {"cmd": "quit"}

Response via stdout:
  {"signature": "abc123...", "timestamp": "1779956218691"}
  {"captcha_param": "eyJ..."}
  {"status": "ready"}
"""
import json
import sys
import time
import uuid
from pathlib import Path

STATE_FILE = Path(__file__).parent / "zaibot_state.json"


def main():
    try:
        from camoufox import Camoufox, DefaultAddons
    except ImportError:
        print(json.dumps({"error": "camoufox not installed"}), flush=True)
        sys.exit(1)

    if not STATE_FILE.exists():
        print(json.dumps({"error": "No saved session. Run: python3 login.py login"}), flush=True)
        sys.exit(1)

    with open(STATE_FILE) as f:
        state = json.load(f)

    with Camoufox(
        headless=False,
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
        context = browser.new_context(storage_state=state)

        # Install persistent fetch interceptor
        context.add_init_script("""
        (function() {
            const origFetch = window.fetch;
            window.__sigData = null;
            window.__captchaParam = null;
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
                    const urlObj = new URL(url);
                    window.__sigData = {
                        signature: headers['x-signature'] || headers['X-Signature'] || '',
                        timestamp: urlObj.searchParams.get('signature_timestamp') || '',
                    };
                    // Capture captcha param from body
                    try {
                        const body = JSON.parse(req.body);
                        if (body.captcha_verify_param) {
                            window.__captchaParam = body.captcha_verify_param;
                        }
                    } catch(e) {}
                }
                return origFetch.apply(this, args);
            };
        })();
        """)

        page = context.new_page()
        page.set_default_timeout(30000)
        page.goto("https://chat.z.ai/", wait_until="domcontentloaded")
        time.sleep(3)

        print(json.dumps({"status": "ready"}), flush=True)

        # Command loop
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                cmd = json.loads(line)
            except json.JSONDecodeError:
                print(json.dumps({"error": "invalid JSON"}), flush=True)
                continue

            action = cmd.get("cmd", "")

            if action == "quit":
                break

            elif action == "status":
                print(json.dumps({"status": "ready"}), flush=True)

            elif action == "captcha_param":
                cp = page.evaluate("window.__captchaParam")
                print(json.dumps({"captcha_param": cp}), flush=True)

            elif action == "sign":
                prompt = cmd.get("prompt", "hello")
                timestamp = cmd.get("timestamp", str(int(time.time() * 1000)))

                # Reset capture
                page.evaluate("window.__sigData = null")

                # Type message
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
                else:
                    # Wait for captcha
                    print(json.dumps({"status": "captcha_needed"}), flush=True)
                    solved = False
                    for _ in range(180):
                        time.sleep(2)
                        send_btn = page.query_selector("#send-message-button")
                        if send_btn and not send_btn.is_disabled():
                            # Re-type and send
                            page.evaluate("""(prompt) => {
                                const textarea = document.querySelector('#chat-input');
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
                            time.sleep(0.3)
                            send_btn.click()
                            solved = True
                            break
                    if not solved:
                        print(json.dumps({"error": "captcha timeout"}), flush=True)
                        continue

                # Wait for signature capture
                sig_data = None
                for _ in range(30):
                    time.sleep(1)
                    sig_data = page.evaluate("window.__sigData")
                    if sig_data and sig_data.get("signature"):
                        break

                if sig_data and sig_data.get("signature"):
                    # Save state
                    new_state = context.storage_state()
                    with open(STATE_FILE, "w") as f:
                        json.dump(new_state, f, indent=2)

                    print(json.dumps({
                        "signature": sig_data["signature"],
                        "timestamp": sig_data.get("timestamp", timestamp),
                        "captcha_param": page.evaluate("window.__captchaParam"),
                    }), flush=True)
                else:
                    print(json.dumps({"error": "signature capture failed"}), flush=True)

                # Wait for response to complete, then navigate back for next request
                time.sleep(5)
                page.goto("https://chat.z.ai/", wait_until="domcontentloaded")
                time.sleep(2)

            else:
                print(json.dumps({"error": f"unknown command: {action}"}), flush=True)


if __name__ == "__main__":
    main()
