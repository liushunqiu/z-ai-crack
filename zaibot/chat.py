#!/usr/bin/env python3
"""Z.ai Chat - hybrid: auto-type + read response from DOM"""
import json, sys, time
from pathlib import Path
from camoufox import Camoufox, DefaultAddons

STATE_FILE = Path(__file__).parent / "zaibot_state.json"

def ask(prompt: str) -> str:
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

        context.add_init_script("""
            window.__fetchUrl = '';
            var _f = window.fetch;
            window.fetch = function() {
                var url = typeof arguments[0] === 'string' ? arguments[0] : (arguments[0]?.url || '');
                if (url.indexOf('/api/v2/chat/completions') !== -1) {
                    window.__fetchUrl = url;
                }
                return _f.apply(this, arguments);
            };
        """)

        page = context.new_page()
        page.set_default_timeout(120000)

        page.goto("https://chat.z.ai/", wait_until="domcontentloaded")
        time.sleep(3)

        # Check for new chat button
        try:
            new_chat = page.query_selector("button:has-text('New Chat'), a:has-text('New Chat'), [class*='new-chat'], [class*='newChat']")
            if new_chat:
                new_chat.click()
                print("[*] Clicked New Chat")
                time.sleep(2)
        except Exception:
            pass

        page.wait_for_selector("#chat-input", timeout=15000)
        page.click("#chat-input")
        time.sleep(0.3)
        page.type("#chat-input", prompt, delay=80)
        time.sleep(0.5)

        send_btn = page.query_selector("#send-message-button")
        if send_btn:
            send_btn.click()
        else:
            page.keyboard.press("Enter")

        print("[*] Sent, waiting for response in DOM...")

        api_detected = False
        prev_len = 0
        timeout = 180

        for i in range(timeout):
            time.sleep(1)

            # Check if API was called
            if not api_detected:
                fetch_url = page.evaluate("window.__fetchUrl")
                if fetch_url:
                    print(f"  [{i}s] API called: ...{fetch_url[-80:]}")
                    api_detected = True

            # Read response from DOM
            body_text = page.evaluate("""() => {
                var msgs = document.querySelectorAll('[class*="message"], [data-testid*="message"], [class*="chat-msg"]');
                if (msgs.length === 0) return '__NOMSGS__';
                var last = msgs[msgs.length - 1];
                var text = last.textContent || '';
                if (last.tagName === 'IMG') return '__IMG__';
                if (text.length < 50 && text.indexOf('data:') < 0) return '__SHORT__' + text;
                return text;
            }""")

            if body_text and body_text not in ('__NOMSGS__', '__IMG__') and not body_text.startswith('__SHORT__'):
                body_text = body_text.strip()
                if len(body_text) > prev_len + 5:
                    prev_len = len(body_text)
                    # Keep waiting if still growing (streaming)
                    if i < timeout - 5:
                        continue

                print(f"[+] Response complete ({i}s, {len(body_text)} chars)")
                return body_text[:10000]

            if not api_detected and body_text == '__NOMSGS__':
                if i > 0 and i % 15 == 0:
                    print(f"  [{i}s] waiting for API call & response...")

        return "[timeout] No response captured"

if __name__ == "__main__":
    if not STATE_FILE.exists():
        print("[x] Run 'python3 login.py login' first")
        sys.exit(1)
    prompt = " ".join(sys.argv[1:]) or "hello"
    reply = ask(prompt)
    print(f"\n=== Reply ===\n{reply}")
