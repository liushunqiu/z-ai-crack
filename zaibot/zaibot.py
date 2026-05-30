#!/usr/bin/env python3
"""
Z.ai API Client - Final version
Uses Camoufox browser to send messages and read responses from DOM.

Usage:
  python3 zaibot.py "你的问题"
  python3 zaibot.py              # interactive mode
"""
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "zaibot_state.json"


def _extract_answer(full_text: str) -> str:
    """Extract the answer portion from the full response text (remove thinking)."""
    if not full_text:
        return ""

    # The response format is:
    # "Thought Process\n\n<thinking content>\n\n<answer>"
    # or "<think>...</think>\n\n<answer>"

    # Try to find the answer after thinking
    markers = ["Thought Process", "<think>"]
    for marker in markers:
        if marker in full_text:
            idx = full_text.index(marker)
            # Find the end of thinking section
            rest = full_text[idx:]
            # The answer is typically the last substantial paragraph
            # after the thinking content
            lines = rest.split("\n")
            # Skip the thinking section and get the answer
            in_thinking = True
            answer_lines = []
            for line in lines:
                stripped = line.strip()
                if in_thinking:
                    # Detect transition from thinking to answer
                    # Answer typically starts after a blank line following thinking
                    if stripped == "" and answer_lines:
                        continue
                    # Check for common answer markers
                    if any(stripped.startswith(m) for m in ["Here", "The answer", "In summary", "Based on"]):
                        in_thinking = False
                        answer_lines.append(stripped)
                    continue
                answer_lines.append(stripped)

            if answer_lines:
                return "\n".join(answer_lines).strip()

    # Fallback: return the last non-empty paragraph
    paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
    if paragraphs:
        return paragraphs[-1]

    return full_text.strip()


def ask(prompt: str, headless: bool = False) -> str:
    """Send a message and get response via browser DOM."""
    if not STATE_FILE.exists():
        raise RuntimeError("No saved session. Run: python3 login.py login")

    try:
        from camoufox import Camoufox, DefaultAddons
    except ImportError:
        raise RuntimeError("camoufox not installed")

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
        page.set_default_timeout(60000)
        page.goto("https://chat.z.ai/", wait_until="domcontentloaded")
        page.wait_for_selector("#chat-input", timeout=30000)
        time.sleep(1)

        # Type message
        page.evaluate("""(prompt) => {
            const textarea = document.querySelector('#chat-input');
            if (!textarea) throw new Error('Chat input not found');
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
            print("[*] Message sent...", file=sys.stderr)
        else:
            print("[!] Waiting for captcha (solve in browser)...", file=sys.stderr)
            for _ in range(180):
                time.sleep(2)
                send_btn = page.query_selector("#send-message-button")
                if send_btn and not send_btn.is_disabled():
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
                    print("[*] Message sent after captcha", file=sys.stderr)
                    break
            else:
                raise RuntimeError("Captcha timeout (3 minutes)")

        # Wait for response to complete
        prev_len = 0
        stable_count = 0
        timeout = 180

        for i in range(timeout):
            time.sleep(2)

            # Read response from #response-content-container
            full_text = page.evaluate("""() => {
                const el = document.querySelector('#response-content-container');
                return el ? el.innerText : '';
            }""")

            if full_text and len(full_text) > 10:
                if len(full_text) > prev_len + 5:
                    prev_len = len(full_text)
                    stable_count = 0
                    continue

                stable_count += 1
                if stable_count >= 4:
                    # Save updated state
                    new_state = context.storage_state()
                    with open(STATE_FILE, "w") as f:
                        json.dump(new_state, f, indent=2)

                    answer = _extract_answer(full_text)
                    return answer if answer else full_text

            if i > 0 and i % 10 == 0:
                print(f"  [{i*2}s] waiting for response...", file=sys.stderr)

        # Final attempt
        final = page.evaluate("""() => {
            const el = document.querySelector('#response-content-container');
            return el ? el.innerText : '';
        }""")
        if final and len(final) > 10:
            answer = _extract_answer(final)
            return answer if answer else final

        raise RuntimeError("Response timeout (3 minutes)")


def main():
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = input("You: ")

    print(f"[*] Asking: {prompt}", file=sys.stderr)
    try:
        reply = ask(prompt)
        print(reply)
    except Exception as e:
        print(f"[x] Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
