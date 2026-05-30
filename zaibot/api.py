#!/usr/bin/env python3
"""
Z.ai API 客户端 - 读取 token 后调 API
用法:
  python3 api.py "你的问题"
"""
import json
import sys
import urllib.request
from pathlib import Path

TOKEN_FILE = Path(__file__).parent / "zaibot_token.txt"

def ask(prompt: str) -> str:
    token = TOKEN_FILE.read_text().strip()
    url = "https://chat.z.ai/api/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = json.dumps({
        "model": "glm-5.1",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }).encode()

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]

if __name__ == "__main__":
    if not TOKEN_FILE.exists():
        print("[x] 请先运行 python3 login.py 登录")
        sys.exit(1)
    prompt = " ".join(sys.argv[1:]) or "你好，请简单介绍一下自己"
    print(ask(prompt))
