#!/usr/bin/env python3
"""Capture real chat/completions request/response in Google Chrome via CDP."""
import json, os, subprocess, time, urllib.request
from pathlib import Path
BASE_DIR=Path(__file__).parent
STATE_FILE=BASE_DIR/'zaibot_state.json'
OUT=BASE_DIR/'captured_chrome_chat.json'
CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

def launch(port):
    return subprocess.Popen([CHROME,f'--remote-debugging-port={port}',f'--user-data-dir={Path.home()}/.config/zaibot-chrome-chat-{port}','--no-first-run','--no-default-browser-check','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def wait(port):
    for _ in range(30):
        time.sleep(1)
        try: urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version',timeout=1).read(); return
        except Exception: pass
    raise RuntimeError('cdp not ready')

def main():
    port=int(os.environ.get('ZAIBOT_CDP_PORT','9350'))
    prompt='hello capture chrome'
    launch(port); wait(port)
    from playwright.sync_api import sync_playwright
    captured={'requests':[],'responses':[],'console':[]}
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp(f'http://127.0.0.1:{port}',timeout=15000)
        ctx=browser.contexts[0]
        if STATE_FILE.exists():
            st=json.loads(STATE_FILE.read_text())
            if st.get('cookies'): ctx.add_cookies(st['cookies'])
        ctx.add_init_script(r"""
        (()=>{
          const of=window.fetch; window.__chatReqs=[];
          window.fetch=function(...args){
            const url=typeof args[0]==='string'?args[0]:(args[0]&&args[0].url)||'';
            const opt=args[1]||{};
            if(url.includes('/chat/completions')){
              let headers={}; const h=opt.headers||{};
              if(h instanceof Headers) h.forEach((v,k)=>headers[k]=v); else headers={...h};
              const rec={url,method:opt.method||'GET',headers,body:opt.body||'',ts:Date.now()};
              window.__chatReqs.push(rec); console.log('[CHAT_CAPTURE]', JSON.stringify(rec));
            }
            return of.apply(this,args);
          };
        })();
        """)
        page=ctx.new_page()
        page.on('console', lambda m: (captured['console'].append(m.text), print(m.text[:500]) if 'CHAT_CAPTURE' in m.text or 'CAPTCHA' in m.text else None))
        def on_req(req):
            if '/chat/completions' in req.url or 'captcha' in req.url or 'device.saf' in req.url:
                captured['requests'].append({'url':req.url,'method':req.method,'headers':dict(req.headers),'body':req.post_data,'ts':time.time()})
                print('[REQ]',req.method,req.url[:180])
        def on_resp(resp):
            if '/chat/completions' in resp.url or 'captcha' in resp.url or 'device.saf' in resp.url:
                body=None
                try: body=resp.text()[:4000]
                except Exception: body='<unavailable>'
                captured['responses'].append({'url':resp.url,'status':resp.status,'headers':dict(resp.headers),'body':body,'ts':time.time()})
                print('[RESP]',resp.status,resp.url[:180], (body or '')[:200].replace('\n',' '))
        page.on('request', on_req); page.on('response', on_resp)
        page.goto('https://chat.z.ai/',wait_until='domcontentloaded',timeout=60000)
        if STATE_FILE.exists():
            st=json.loads(STATE_FILE.read_text())
            for origin in st.get('origins',[]):
                if origin.get('origin')=='https://chat.z.ai':
                    for item in origin.get('localStorage',[]):
                        page.evaluate('([k,v])=>localStorage.setItem(k,v)', [item.get('name'), item.get('value')])
                    page.reload(wait_until='domcontentloaded',timeout=60000)
                    break
        page.wait_for_selector('#chat-input',timeout=60000)
        time.sleep(5)
        page.evaluate("""(prompt)=>{
          const t=document.querySelector('#chat-input');
          t.focus();
          Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(t,prompt);
          t.dispatchEvent(new InputEvent('input',{bubbles:true,cancelable:true,inputType:'insertText',data:prompt}));
        }""", prompt)
        time.sleep(0.5)
        btn=page.query_selector('#send-message-button')
        print('[*] btn disabled?', btn.is_disabled() if btn else None)
        if btn: btn.click()
        for i in range(120):
            time.sleep(1)
            reqs=page.evaluate('window.__chatReqs || []')
            if reqs:
                captured['page_chat_reqs']=reqs
                break
        time.sleep(8)
        OUT.write_text(json.dumps(captured,indent=2,ensure_ascii=False),encoding='utf-8')
        print('[+] saved',OUT)
        browser.close()
if __name__=='__main__': main()
