#!/usr/bin/env python3
import json, os, subprocess, time, urllib.request
from pathlib import Path
CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
port=int(os.environ.get('ZAIBOT_CDP_PORT','9333'))
print('[1] chrome exists', os.path.exists(CHROME), flush=True)
proc=subprocess.Popen([CHROME,f'--remote-debugging-port={port}',f'--user-data-dir={Path.home()}/.config/zaibot-chrome-debug-{port}','--no-first-run','--no-default-browser-check','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print('[2] launched pid', proc.pid, 'port', port, flush=True)
for i in range(20):
    time.sleep(1)
    try:
        data=urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version',timeout=1).read().decode()
        print('[3] cdp ok', data[:200], flush=True)
        break
    except Exception as e:
        print('[wait]', i, repr(e), flush=True)
else:
    raise SystemExit('cdp not up')
from playwright.sync_api import sync_playwright
print('[4] import playwright ok', flush=True)
with sync_playwright() as p:
    print('[5] connecting', flush=True)
    browser=p.chromium.connect_over_cdp(f'http://127.0.0.1:{port}', timeout=10000)
    print('[6] connected contexts', len(browser.contexts), flush=True)
    ctx=browser.contexts[0]
    page=ctx.new_page()
    print('[7] goto', flush=True)
    page.goto('https://chat.z.ai/', wait_until='domcontentloaded', timeout=60000)
    print('[8] url', page.url, flush=True)
