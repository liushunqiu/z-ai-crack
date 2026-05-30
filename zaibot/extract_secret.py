#!/usr/bin/env python3
"""
Extract the HMAC secret from z.ai's frontend JS by hooking CryptoJS.
Run this in a Camoufox browser to capture the HMAC key used for signing.
"""
import json
import time
from pathlib import Path
from camoufox import Camoufox, DefaultAddons

STATE_FILE = Path(__file__).parent / "zaibot_state.json"


def extract():
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

        # Hook CryptoJS HMAC to capture the key
        context.add_init_script("""
        // Wait for CryptoJS to load, then hook it
        const origDefine = Object.defineProperty;
        let hmacCaptures = [];
        window.__hmacCaptures = hmacCaptures;

        // Hook the global to find CryptoJS when it's assigned
        let _origHMAC = null;
        const hookCryptoJS = () => {
            // Search all script-loaded globals
            for (const key of Object.keys(window)) {
                const obj = window[key];
                if (obj && typeof obj === 'object' && obj.HMAC && obj.SHA256 && obj.enc) {
                    // Found CryptoJS!
                    console.log('[SECRET] Found CryptoJS at window.' + key);
                    const origHMAC = obj.HMAC;
                    obj.HMAC = function(algo, message, key) {
                        const result = origHMAC.apply(this, arguments);
                        const keyStr = typeof key === 'string' ? key : (key?.toString() || '');
                        const msgStr = typeof message === 'string' ? message : (message?.toString() || '');
                        hmacCaptures.push({
                            algo: typeof algo === 'string' ? algo : algo?.toString(),
                            key: keyStr,
                            message: msgStr,
                            result: result.toString(),
                        });
                        console.log('[SECRET] HMAC captured: key=' + keyStr.substring(0, 50) + ' msg=' + msgStr.substring(0, 80));
                        return result;
                    };
                    break;
                }
            }
        };

        // Try hooking immediately and also after a delay
        setTimeout(hookCryptoJS, 1000);
        setTimeout(hookCryptoJS, 3000);
        setTimeout(hookCryptoJS, 5000);
        """)

        page = context.new_page()
        page.goto("https://chat.z.ai/", wait_until="domcontentloaded")
        time.sleep(5)

        # Type and send
        page.evaluate("""() => {
            const textarea = document.querySelector('#chat-input');
            if (!textarea) return;
            textarea.focus();
            const nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            nativeSetter.call(textarea, 'test123');
            textarea.dispatchEvent(new InputEvent('input', {
                bubbles: true, cancelable: true,
                inputType: 'insertText', data: 'test123'
            }));
        }""")
        time.sleep(0.5)

        send_btn = page.query_selector("#send-message-button")
        if send_btn and not send_btn.is_disabled():
            send_btn.click()
            print("[*] Message sent, waiting for HMAC capture...")
        else:
            print("[!] Waiting for captcha...")
            for _ in range(120):
                time.sleep(2)
                send_btn = page.query_selector("#send-message-button")
                if send_btn and not send_btn.is_disabled():
                    page.evaluate("""() => {
                        const textarea = document.querySelector('#chat-input');
                        textarea.focus();
                        const nativeSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLTextAreaElement.prototype, 'value'
                        ).set;
                        nativeSetter.call(textarea, 'test123');
                        textarea.dispatchEvent(new InputEvent('input', {
                            bubbles: true, cancelable: true,
                            inputType: 'insertText', data: 'test123'
                        }));
                    }""")
                    time.sleep(0.3)
                    send_btn.click()
                    break

        # Wait for HMAC captures
        for i in range(30):
            time.sleep(1)
            captures = page.evaluate("window.__hmacCaptures || []")
            if captures and len(captures) > 0:
                print(f"\n[+] Captured {len(captures)} HMAC calls!")
                for j, cap in enumerate(captures):
                    print(f"\n--- HMAC Call #{j+1} ---")
                    print(f"  Algorithm: {cap.get('algo')}")
                    print(f"  Key: {cap.get('key')}")
                    print(f"  Message: {cap.get('message')[:200]}")
                    print(f"  Result: {cap.get('result')}")

                # Save to file
                out_file = Path(__file__).parent / "hmac_secret.json"
                with open(out_file, "w") as f:
                    json.dump(captures, f, indent=2)
                print(f"\n[+] Saved to {out_file}")
                break

        if not captures:
            print("[!] No HMAC captures. CryptoJS might be loaded differently.")
            # Try alternative: check if iS is accessible
            alt = page.evaluate("""() => {
                // Try to find the module by checking __webpack_modules__
                const mods = typeof __webpack_modules__ !== 'undefined' ? Object.keys(__webpack_modules__) : [];
                return { webpackModules: mods.length };
            }""")
            print(f"  Webpack modules: {alt}")

        input("\nPress Enter to close...")


if __name__ == "__main__":
    extract()
