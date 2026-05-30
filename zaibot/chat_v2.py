#!/usr/bin/env python3
"""
Z.ai Chat - v2: Browser-based with proper session handling
Uses Camoufox to send messages and read responses from the DOM.
Handles captcha by waiting for user to solve it.
"""
import json
import sys
import time
from pathlib import Path
from camoufox import Camoufox, DefaultAddons

STATE_FILE = Path(__file__).parent / "zaibot_state.json"


def ask(prompt: str, headless: bool = False) -> str:
    if not STATE_FILE.exists():
        print("[x] No saved session. Run: python3 login.py login")
        sys.exit(1)

    with open(STATE_FILE) as f:
        state = json.load(f)

    with Camoufox(
        headless=headless,
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
        page = context.new_page()
        page.set_default_timeout(120000)

        # Navigate to chat
        page.goto("https://chat.z.ai/", wait_until="domcontentloaded")
        time.sleep(3)

        # Wait for chat input
        page.wait_for_selector("#chat-input", timeout=15000)

        # Type message using native setter (works with Svelte)
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
        time.sleep(0.5)

        # Click send
        send_btn = page.query_selector("#send-message-button")
        if send_btn and not send_btn.is_disabled():
            send_btn.click()
            print("[*] Message sent, waiting for response...")
        else:
            print("[!] Send button disabled - captcha may be required")
            print("[!] Please solve the captcha in the browser")
            # Wait for user to solve captcha and send
            for i in range(120):
                time.sleep(2)
                send_btn = page.query_selector("#send-message-button")
                if send_btn and not send_btn.is_disabled():
                    # Check if textarea has content
                    val = page.evaluate("document.querySelector('#chat-input')?.value || ''")
                    if val.strip():
                        send_btn.click()
                        print("[*] Message sent after captcha")
                        break
                # Check if response already appeared (user sent manually)
                msgs = page.evaluate("""() => {
                    const els = document.querySelectorAll('[class*="message"]');
                    return els.length;
                }""")
                if msgs > 1:
                    print("[*] Response detected")
                    break

        # Wait for response
        prev_len = 0
        stable_count = 0
        timeout = 180

        for i in range(timeout):
            time.sleep(1)

            # Read last assistant message from DOM
            body_text = page.evaluate("""() => {
                // Try various selectors for assistant messages
                const selectors = [
                    '.assistant-message',
                    '[data-role="assistant"]',
                    '[class*="assistant"]',
                    '.message-content',
                    '[class*="markdown"]',
                ];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    if (els.length > 0) {
                        const last = els[els.length - 1];
                        const text = last.textContent?.trim();
                        if (text && text.length > 10) return text;
                    }
                }
                // Fallback: get all text blocks
                const allMsgs = document.querySelectorAll('[class*="message"], [data-testid*="message"]');
                if (allMsgs.length >= 2) {
                    const last = allMsgs[allMsgs.length - 1];
                    return last.textContent?.trim() || '';
                }
                return '';
            }""")

            if body_text and len(body_text) > 10:
                if len(body_text) > prev_len + 5:
                    prev_len = len(body_text)
                    stable_count = 0
                    if i < timeout - 5:
                        continue
                else:
                    stable_count += 1
                    if stable_count >= 3:
                        print(f"[+] Response complete ({i}s, {len(body_text)} chars)")
                        return body_text[:10000]

            if i > 0 and i % 15 == 0:
                print(f"  [{i}s] waiting for response...")

        return "[timeout] No response captured"


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) or "hello, say hi in 5 words"
    reply = ask(prompt)
    print(f"\n=== Reply ===\n{reply}")
