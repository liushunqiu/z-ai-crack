#!/usr/bin/env python3
"""
Capture a real chat.z.ai API request by intercepting browser traffic.
1. Opens Camoufox browser (visible) with saved session
2. Navigates to chat.z.ai (chat page)
3. Intercepts /api/v2/chat/completions requests
4. Waits for you to type & send a message (solving captcha manually)
5. Prints captured request details for replay
"""
import json
import sys
from pathlib import Path
from camoufox import Camoufox
import logging
_logger = logging.getLogger(__name__)


STATE_FILE = Path(__file__).parent / "zaibot_state.json"
TOKEN_FILE = Path(__file__).parent / "zaibot_token.txt"

def capture():
    _logger.info("=" * 60)
    _logger.info("  Camoufox 请求捕获器")
    _logger.info("=" * 60)
    _logger.info("  [1] 浏览器已打开到 chat.z.ai (聊天页面)")
    _logger.info("  [2] 请在聊天框输入消息并点击发送")
    _logger.info("  [3] 如果弹出验证码，请手动完成")
    _logger.info("  [4] 脚本会自动捕获 API 请求并保存")
    _logger.info("  [5] 完成后请关闭浏览器")
    _logger.info("=" * 60)

    captured_data = {"requests": []}

    with Camoufox(headless=False, geoip=False) as browser:
        context = browser.new_context(
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
        )
        page = context.new_page()

        # Intercept network requests
        def handle_request(request):
            url = request.url
            if "chat/completions" in url:
                headers = dict(request.headers)
                body = request.post_data
                data = {
                    "url": url,
                    "method": request.method,
                    "headers": headers,
                    "body": body,
                }
                captured_data["requests"].append(data)
                _logger.info(f"\n[✓] 捕获到请求: {url[:120]}")
                _logger.info(f"    X-Signature: {headers.get('X-Signature', 'N/A')[:50]}")
                _logger.info(f"    Body 长度: {len(body) if body else 0}")
                with open(Path(__file__).parent / "captured_request.json", "w") as f:
                    json.dump(captured_data, f, indent=2, ensure_ascii=False)
                _logger.info("[✓] 已保存到 captured_request.json")

        page.on("request", handle_request)

        page.goto("https://chat.z.ai")
        page.wait_for_load_state("networkidle")
        _logger.info("[*] 页面已加载，请在浏览器中操作...")

        input("\n按 Enter 键退出...")

    _logger.info(f"\n[✓] 共捕获 {len(captured_data['requests'])} 个请求")
    if captured_data["requests"]:
        _logger.info("[✓] 详细数据已保存到 captured_request.json")

if __name__ == "__main__":
    capture()
