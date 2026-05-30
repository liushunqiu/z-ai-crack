#!/usr/bin/env python3
"""
Z.ai 自动登录脚本 - Camoufox Session 持久化方案
首次运行：手动过验证码登录，保存 session
后续运行：直接恢复 session 取 token
"""
import json
import os
import sys
from pathlib import Path
from camoufox import Camoufox

STATE_FILE = Path(__file__).parent / "zaibot_state.json"
TOKEN_FILE = Path(__file__).parent / "zaibot_token.txt"

def get_user_role(token):
    """通过 API 检查当前用户的 role，排除游客"""
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://chat.z.ai/api/v1/auths/",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
        return result.get("role")
    except:
        return None

def is_real_user(role):
    return role and role != "guest"

def launch_and_login():
    """启动浏览器，让用户手动登录，等待真实账号登录后保存"""
    print("[*] 启动 Camoufox 浏览器...")
    print("=" * 50)
    print("  [1] 浏览器已打开到 chat.z.ai/auth")
    print("  [2] 请在页面中输入你的 **邮箱和密码**")
    print("  [3] 手动完成 **滑块验证码**")
    print("  [4] 点击登录，脚本会自动检测真实登录态并保存")
    print("  ⚠️  请不要关闭浏览器，等待自动保存完成")
    print("=" * 50)

    with Camoufox(headless=False, geoip=False) as browser:
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://chat.z.ai/auth")
        page.wait_for_load_state("networkidle")

        import time
        real_token = None
        for _ in range(600):
            time.sleep(2)
            token = page.evaluate("localStorage.getItem('token')")
            if token and token.strip():
                token = token.strip()
                role = get_user_role(token)
                if is_real_user(role):
                    real_token = token
                    print(f"\n[✓] 检测到真实用户登录! (role: {role})")
                    break
                else:
                    if _ % 10 == 0:
                        print(f"[*] 当前为游客模式 (role: {role})，等待真实登录...")

        if not real_token:
            print("\n[x] 等待登录超时 (10分钟)，请重试")
            return

        state = context.storage_state()
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        print(f"[✓] Session 已保存到 {STATE_FILE}")

        with open(TOKEN_FILE, "w") as f:
            f.write(real_token)
        print(f"[✓] Token 已保存到 {TOKEN_FILE}")
        print(f"[✓] Token: {real_token[:40]}...")

def restore_and_get_token():
    """恢复 Session 并获取 token"""
    if not STATE_FILE.exists():
        print("[x] 未找到保存的 Session 文件，请先运行首次登录")
        return None

    print("[*] 恢复浏览器 Session...")
    with open(STATE_FILE) as f:
        state = json.load(f)

    with Camoufox(headless=True, geoip=False) as browser:
        context = browser.new_context(storage_state=state)
        page = context.new_page()
        page.goto("https://chat.z.ai/auth")
        page.wait_for_load_state("networkidle")

        token = page.evaluate("localStorage.getItem('token')")
        if token:
            with open(TOKEN_FILE, "w") as f:
                f.write(token.strip())
            print(f"[✓] Token 有效: {token[:40]}...")
            return token.strip()
        else:
            print("[x] Token 已过期，请重新运行首次登录")
            return None

def test_api_call(token):
    """用 token 验证登录状态和可用模型"""
    import urllib.request

    print("[*] 验证登录状态...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    req = urllib.request.Request("https://chat.z.ai/api/v1/auths/", headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            session = json.loads(resp.read())
            role = session.get("role", "?")
            email = session.get("email", "?")
            name = session.get("name", "?")
            print(f"[✓] 登录身份: {name} ({email}) | role: {role}")
    except Exception as e:
        print(f"[x] 获取会话失败: {e}")
        return

    print("[*] 获取可用模型...")
    try:
        req = urllib.request.Request("https://chat.z.ai/api/models", headers=headers)
        with urllib.request.urlopen(req) as resp:
            models = json.loads(resp.read())
        model_ids = [m["id"] for m in models.get("data", [])]
        print(f"[✓] 可用模型 ({len(model_ids)} 个):")
        for m in model_ids[:5]:
            print(f"     - {m}")
        if len(model_ids) > 5:
            print(f"     ... 还有 {len(model_ids)-5} 个")
    except Exception as e:
        print(f"[x] 获取模型列表失败: {e}")

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    print("=== Z.ai 自动登录工具 ===")

    if mode == "1" or mode == "login":
        launch_and_login()
    elif mode == "2" or mode == "restore":
        restore_and_get_token()
    elif mode == "3" or mode == "test":
        if TOKEN_FILE.exists():
            token = TOKEN_FILE.read_text().strip()
            test_api_call(token)
        else:
            print("[x] 请先运行 python3 login.py login 登录")
    else:
        print("用法: python3 login.py [login|restore|test]")
        print("  login   - 首次登录（手动过验证码）")
        print("  restore - 恢复 Session 取 Token")
        print("  test    - 测试 API 调用")
