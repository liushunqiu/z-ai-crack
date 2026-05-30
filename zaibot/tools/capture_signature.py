#!/usr/bin/env python3
"""
Capture the real chat.z.ai API request (headers + body) by intercepting fetch.
Opens Camoufox browser (visible), loads saved session, waits for you to send a message.
Captures the full request including X-Signature, X-FE-Version, etc.
Saves to captured_request.json for replay.
"""
import json
import sys
import time
from pathlib import Path
from camoufox import Camoufox, DefaultAddons

STATE_FILE = Path(__file__).parent / "zaibot_state.json"
OUTPUT_FILE = Path(__file__).parent / "captured_request.json"
SIGNATURE_CACHE_FILE = Path(__file__).parent / "zaibot_signature_cache.json"

def capture():
    if not STATE_FILE.exists():
        print("[x] No saved session. Run: python3 login.py login")
        sys.exit(1)

    with open(STATE_FILE) as f:
        state = json.load(f)

    print("=" * 60)
    print("  Camoufox Signature Capture")
    print("=" * 60)
    print("  [1] Browser will open to chat.z.ai")
    print("  [2] Type a message and click Send")
    print("  [3] If captcha appears, solve it manually")
    print("  [4] Request will be auto-captured")
    print("  [5] Close browser when done (or press Ctrl+C)")
    print("=" * 60)

    captured = {"requests": []}

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
        page = context.new_page()

        # Inject fetch interceptor BEFORE navigation
        page.add_init_script("""
            const origFetch = window.fetch;
            window.__capturedRequests = [];
            window.fetch = function(...args) {
                const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
                if (url.includes('chat/completions')) {
                    const req = args[1] || {};
                    let headers = {};
                    if (req.headers) {
                        if (req.headers instanceof Headers) {
                            req.headers.forEach((v, k) => headers[k] = v);
                        } else if (typeof req.headers === 'object') {
                            headers = {...req.headers};
                        }
                    }
                    const captured = {
                        url: url,
                        method: req.method || 'POST',
                        headers: headers,
                        body: req.body || null,
                        timestamp: Date.now()
                    };
                    window.__capturedRequests.push(captured);
                    console.log('[CAPTURE]', JSON.stringify(captured));
                }
                return origFetch.apply(this, args);
            };
        """)

        page.on("console", lambda msg: (
            print(f"  [console] {msg.text[:200]}")
            if "[CAPTURE]" in msg.text else None
        ))

        page.goto("https://chat.z.ai/", wait_until="domcontentloaded")
        time.sleep(3)

        # Try clicking "New Chat" if visible
        try:
            new_chat = page.query_selector("button:has-text('New Chat'), a:has-text('New Chat')")
            if new_chat:
                new_chat.click()
                print("[*] Clicked New Chat")
                time.sleep(2)
        except Exception:
            pass

        print("[*] Ready. Type a message in the browser and click Send.")
        print("[*] Waiting for API request capture...")
        print()

        # Poll for captured requests
        try:
            while True:
                time.sleep(2)
                requests = page.evaluate("window.__capturedRequests || []")
                if requests and len(requests) > len(captured["requests"]):
                    new_reqs = requests[len(captured["requests"]):]
                    for req in new_reqs:
                        captured["requests"].append(req)
                        print(f"\n[✓] CAPTURED REQUEST!")
                        print(f"    URL: {req['url'][:120]}")
                        print(f"    Method: {req['method']}")
                        print(f"    Headers:")
                        for k, v in req.get("headers", {}).items():
                            val = str(v)
                            if len(val) > 80:
                                val = val[:80] + "..."
                            print(f"      {k}: {val}")
                        body = req.get("body", "")
                        if body:
                            try:
                                body_json = json.loads(body)
                                print(f"    Body model: {body_json.get('model')}")
                                print(f"    Body messages: {len(body_json.get('messages', []))} msgs")
                                print(f"    Body stream: {body_json.get('stream')}")
                            except:
                                print(f"    Body length: {len(body)}")

                        # Save immediately
                        with open(OUTPUT_FILE, "w") as f:
                            json.dump(captured, f, indent=2, ensure_ascii=False)

                        # Also save the latest signature in the API client's cache format.
                        try:
                            from urllib.parse import urlparse, parse_qs
                            headers_l = {str(k).lower(): v for k, v in req.get("headers", {}).items()}
                            sig = headers_l.get("x-signature")
                            qs = parse_qs(urlparse(req.get("url", "")).query)
                            sig_ts = (qs.get("signature_timestamp") or [str(req.get("timestamp") or "")])[0]
                            if sig and sig_ts:
                                with open(SIGNATURE_CACHE_FILE, "w") as sf:
                                    json.dump({
                                        "signature": sig,
                                        "signature_timestamp": sig_ts,
                                        "created_at": time.time(),
                                        "source": "capture_signature.py",
                                    }, sf, indent=2)
                                print(f"[✓] Signature cache saved to {SIGNATURE_CACHE_FILE}")
                        except Exception as e:
                            print(f"[!] Signature cache save skipped: {e}")

                        print(f"[✓] Saved to {OUTPUT_FILE}")

        except KeyboardInterrupt:
            print("\n[*] Interrupted by user")

    print(f"\n[✓] Total captured: {len(captured['requests'])} requests")
    if captured["requests"]:
        print(f"[✓] Data saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    capture()
