#!/usr/bin/env python3
"""Analyze Aliyun/FeiLin captcha flow in real Google Chrome via CDP.

This uses the same environment that previously generated securityToken.
It records request/response metadata plus JS-level hooks for btoa/fetch/XHR and
writes zaibot/captcha_analysis_chrome.json.
"""
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
OUTPUT_FILE = BASE_DIR / "captcha_analysis_chrome.json"
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
]


def find_chrome():
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return None


def launch_chrome(port: int):
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Chrome not found")
    # Use a per-port profile so Chrome always starts a process with the requested CDP port.
    user_data_dir = Path.home() / ".config" / f"zaibot-chrome-captcha-{port}"
    return subprocess.Popen([
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    port = int(os.environ.get("ZAIBOT_CDP_PORT", "9223"))
    proc = launch_chrome(port)
    print(f"[*] launched Chrome pid={proc.pid} port={port}", flush=True)
    # Wait until CDP endpoint is reachable.
    import urllib.request
    for i in range(30):
        time.sleep(1)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).read()
            print("[*] CDP ready", flush=True)
            break
        except Exception as e:
            if i % 5 == 0:
                print(f"[*] waiting CDP {i}s: {e}", flush=True)
    else:
        raise RuntimeError(f"CDP port {port} not reachable")

    from playwright.sync_api import sync_playwright
    captured = {"requests": [], "responses": [], "console": [], "verify_params": []}

    with sync_playwright() as p:
        print("[*] connecting playwright CDP", flush=True)
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=15000)
        print("[*] connected", flush=True)
        context = browser.contexts[0] if browser.contexts else browser.new_context()

        context.add_init_script(r"""
        (() => {
          window.__zaibotCaptchaTrace = {btoa: [], fetch: [], xhr: [], errors: []};
          const interesting = (s) => /captcha|aliyun|aliyuncs|device|saf|cloudauth|certify|verify|chat\/completions/i.test(String(s||''));
          const ob = window.btoa;
          window.btoa = function(s) {
            const out = ob.call(this, s);
            try {
              if (String(s).includes('certifyId') || String(s).includes('DeviceToken') || String(s).includes('sceneId')) {
                window.__zaibotCaptchaTrace.btoa.push({input: String(s), output: out, ts: Date.now()});
                console.log('[ZAIBOT_BTOA]', out, String(s).slice(0, 500));
              }
            } catch(e) {}
            return out;
          };
          const of = window.fetch;
          window.fetch = function(...args) {
            try {
              const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
              const opt = args[1] || {};
              if (interesting(url)) {
                window.__zaibotCaptchaTrace.fetch.push({url, method: opt.method || 'GET', body: opt.body || '', ts: Date.now()});
                console.log('[ZAIBOT_FETCH]', opt.method || 'GET', url, String(opt.body || '').slice(0, 300));
              }
            } catch(e) { window.__zaibotCaptchaTrace.errors.push(String(e)); }
            return of.apply(this, args);
          };
          const xo = XMLHttpRequest.prototype.open;
          const xs = XMLHttpRequest.prototype.send;
          XMLHttpRequest.prototype.open = function(m,u,...rest){ this.__z_m=m; this.__z_u=u; return xo.call(this,m,u,...rest); };
          XMLHttpRequest.prototype.send = function(body){
            try { if (interesting(this.__z_u)) { window.__zaibotCaptchaTrace.xhr.push({url:this.__z_u, method:this.__z_m, body: String(body||''), ts:Date.now()}); console.log('[ZAIBOT_XHR]', this.__z_m, this.__z_u, String(body||'').slice(0,300)); } } catch(e) {}
            return xs.call(this, body);
          };
        })();
        """)

        page = None
        for pg in context.pages:
            if "chat.z.ai" in pg.url:
                page = pg
                break
        if page is None:
            page = context.new_page()

        def on_request(req):
            url = req.url
            if any(k in url.lower() for k in ["captcha", "aliyun", "aliyuncs", "device", "saf", "cloudauth", "certify", "verify", "chat/completions"]):
                rec = {"url": url, "method": req.method, "headers": dict(req.headers), "body": req.post_data, "ts": time.time()}
                captured["requests"].append(rec)
                print(f"[REQ] {req.method} {url[:160]}")
                if req.post_data:
                    print(f"      body {req.post_data[:300]}")

        def on_response(resp):
            url = resp.url
            if any(k in url.lower() for k in ["captcha", "aliyun", "aliyuncs", "device", "saf", "cloudauth", "certify", "verify", "chat/completions"]):
                body = None
                try:
                    txt = resp.text()
                    body = txt[:4000]
                except Exception:
                    body = "<binary/unavailable>"
                captured["responses"].append({"url": url, "status": resp.status, "headers": dict(resp.headers), "body": body, "ts": time.time()})
                print(f"[RESP] {resp.status} {url[:160]}")

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("console", lambda msg: (captured["console"].append(msg.text), print(msg.text[:500]) if "ZAIBOT" in msg.text or "CAPTCHA" in msg.text else None))

        page.goto("https://chat.z.ai/", wait_until="domcontentloaded")
        page.wait_for_selector("#chat-input", timeout=60000)
        time.sleep(3)

        # Force SDK load and trigger captcha UI directly.
        page.evaluate(r"""
        async () => {
          window.__captchaResults = [];
          window.__captchaErrors = [];
          for (const id of ['chat-captcha-element', 'chat-captcha-trigger']) {
            if (!document.getElementById(id)) {
              const el = document.createElement(id === 'chat-captcha-trigger' ? 'button' : 'div');
              el.id = id; document.body.appendChild(el);
            }
          }
          window.AliyunCaptchaConfig = {region: 'sgp', prefix: 'no8xfe'};
          if (typeof initAliyunCaptcha !== 'function') {
            await new Promise((resolve, reject) => {
              const old = document.querySelector('script[src*="AliyunCaptcha.js"]');
              if (old) { old.addEventListener('load', resolve); old.addEventListener('error', reject); return; }
              const s = document.createElement('script');
              s.src = 'https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js';
              s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
            });
          }
          if (typeof initAliyunCaptcha !== 'function') { console.log('[CAPTCHA_ERR]', 'initAliyunCaptcha missing after load'); return; }
          initAliyunCaptcha({
            SceneId: 'didk33e0', mode: 'popup', element: '#chat-captcha-element', button: '#chat-captcha-trigger',
            language: 'en', timeout: 120000, delayBeforeSuccess: false,
            success: (p) => { window.__captchaResults.push(p); console.log('[CAPTCHA_OK]', p); },
            fail: (e) => { window.__captchaErrors.push(e); console.log('[CAPTCHA_FAIL]', JSON.stringify(e)); },
            onError: (e) => { window.__captchaErrors.push(e); console.log('[CAPTCHA_ERR]', JSON.stringify(e)); },
            getInstance: (inst) => { window.__captchaInstance = inst; console.log('[CAPTCHA_INST]'); },
          });
        }
        """)
        time.sleep(15)
        page.evaluate("document.getElementById('chat-captcha-trigger').click()")
        print("[*] 如果弹出滑块，请在 Chrome 里手动完成。等待最多 180 秒...")

        for i in range(90):
            time.sleep(2)
            results = page.evaluate("window.__captchaResults || []")
            if results:
                raw = results[0]
                try:
                    decoded = json.loads(base64.b64decode(raw))
                except Exception:
                    decoded = None
                captured["verify_params"].append({"raw": raw, "decoded": decoded, "ts": time.time()})
                print("[+] captcha solved", decoded)
                break
            if i % 10 == 0:
                errors = page.evaluate("window.__captchaErrors || []")
                trace = page.evaluate("window.__zaibotCaptchaTrace || {}")
                print(f"  [{i*2}s] waiting errors={errors} trace_counts={{k: len(v) if isinstance(v, list) else v for k,v in trace.items()}}")

        captured["page_trace"] = page.evaluate("window.__zaibotCaptchaTrace || {}")
        OUTPUT_FILE.write_text(json.dumps(captured, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[+] saved {OUTPUT_FILE}")
        browser.close()
    # keep Chrome process; user may want it. Do not terminate.
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
