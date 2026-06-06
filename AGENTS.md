# AGENTS.md

This file provides guidance to the AI agent when working with code in this repository.

## Repository Structure

This is a Python monorepo with three sub-projects:

- `zaibot/` — Core Z.ai HTTP API client (signature, captcha, chat).
- `zaibot-bridge/` — OpenAI-compatible FastAPI bridge (multi-account, admin UI).
- `camoufox-reverse-mcp/` — MCP server for Camoufox anti-detection browser reverse engineering.

## Virtual Environments

- **Root `.venv/`** is shared by `zaibot/` and `zaibot-bridge/`. Use it when working on those two projects.
- **`.venv/` inside `camoufox-reverse-mcp/`** is separate. Use it only for that project.
- Do not merge dependencies across the two venvs.

## Imports

Sibling imports between `zaibot/` and `zaibot-bridge/` are done via `sys.path.insert(0, ...)` at module top. This is intentional; do not refactor into installable packages or relative imports.

## Style

- Every Python file starts with `from __future__ import annotations`.
- Type hints use `|` union syntax (requires Python 3.10+).
- Docstrings and comments are in Chinese; keep them that way.

## Secrets & Git

- `.env` contains live Alibaba Cloud credentials. Never commit it.
- `zaibot-bridge/data/` contains per-account cookies and JWT tokens. Never commit it.
- `zaibot/zaibot_state.json`, `zaibot_token.txt`, and `*cache.json` files are gitignored for the same reason.

## Running / Testing

- Start the bridge: `cd zaibot-bridge && ./start.sh` (activates root venv, checks for token, then runs `python3 server.py`).
- Start camoufox-reverse-mcp: `cd camoufox-reverse-mcp && .venv/bin/python -m camoufox_reverse_mcp`.
- Run unit tests: `cd camoufox-reverse-mcp && .venv/bin/pytest`.
- `zaibot/` and `zaibot-bridge/` have no automated test suite; they rely on manual scripts like `zaibot/test_chrome_works.py` and `zaibot/check_network.py`.

## Environment Variables

- `ZAIBOT_USE_PURE_HTTP=1` — Forces `zaibot-bridge` chat requests through `urllib` instead of Camoufox fetch. Useful when DOM-fetch hits F018 but pure HTTP works.
- `ZAIBOT_HMAC_SECRET` — Optional override for X-Signature HMAC key.

## Architecture Gotchas

- **Sticky binding**: `session_id` in API requests maps permanently to one Z.ai account via round-robin on first use. Changing the binding resets the conversation (`chat_id`).
- **Captcha tokens are single-use**: Every chat completion request mints a fresh captcha token via per-account Camoufox browser.
- **IP-level rate limiting**: `AccountManager` enforces a global cooldown across all accounts when multiple accounts fail in a short window.

## Troubleshooting Runbook

遇到以下错误时，按对应方案快速修复：

### `ModuleNotFoundError: No module named 'zaibot'`
**原因**: `server.py` 的 `sys.path` 只包含 bridge 目录，缺少项目根目录。
**修复**: 确保 `server.py` 同时插入两个路径：
```python
sys.path.insert(0, os.path.dirname(__file__))              # bridge 目录
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # 项目根目录
```

### `NameError: name 'Path' is not defined`
**原因**: `runtime.py` 使用了 `pathlib.Path` 但未导入。
**修复**: 在文件顶部添加 `from pathlib import Path`。

### `name 'queue' is not defined`
**原因**: `captcha_service.py` 使用了 `queue.Queue` 但未导入。
**修复**: 在文件顶部添加 `import queue`。

### `没有可用 X-Signature`
**原因**: HMAC 密钥未设置且签名缓存已过期（300s TTL）。
**快速修复方案（按优先级）**:
1. **设置 HMAC 密钥** (长期): `export ZAIBOT_HMAC_SECRET=<secret>`
2. **重新抓取签名** (临时，5 分钟有效):
   - 用 Camoufox MCP 打开 `https://chat.z.ai/`
   - 设置 `localStorage.token` 为有效 JWT
   - 触发一次聊天请求
   - 从网络拦截中复制 `x-signature` 头到 `zaibot/captured_request.json`
3. **删除过期缓存**: `rm -f zaibot/zaibot_signature_cache.json`（让系统回退到 captured_request.json）

### `captcha 生成失败 (send button 持续 disabled)`
**原因**: Camoufox 无法在 Z.ai 页面上触发发送按钮。
**排查步骤**:
1. 确认 `import queue` 存在（常见缺失导入）
2. 检查账号 state 文件: `zaibot-bridge/data/accounts/<account>/state.json`
3. 用 Camoufox MCP 手动打开页面验证登录状态
4. 检查 Camoufox 版本兼容性

### `IP 级别风控冷却中`
**原因**: 多个账号在短时间内连续失败，触发全局 30 分钟冷却。
**处理**: 等待冷却结束，或重启服务清除内存中的冷却状态（不推荐频繁操作）。

### Z.ai Token 过期 / 401
**原因**: Z.ai JWT token 被服务端撤销。
**修复**: `cd zaibot && python3 login.py login` 重新登录获取新 token。
**注意**: Z.ai JWT payload 中没有 `exp` 字段，但服务端可能在版本更新时批量失效。

## E2E Verification Checklist

新增代码或修复 bug 后，按此清单验证完整链路：

```bash
# 1. 环境预检
cd zaibot-bridge && ../.venv/bin/python3 -c "
from zaibot import zaibot_core
from zaibot.captcha_service import CaptchaSession
from bridge.runtime import ChatRuntimeService
from pathlib import Path
import queue
print('All imports OK')
"

# 2. 启动服务
ZAIBOT_USE_PURE_HTTP=1 ../.venv/bin/python3 server.py &
sleep 3

# 3. 检查状态
curl -s http://localhost:8001/api/status | python3 -m json.tool

# 4. 非流式测试
curl -s --max-time 120 -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"GLM-5.1","messages":[{"role":"user","content":"回复两个字：你好"}],"stream":false,"session_id":"test-e2e"}'

# 5. 流式测试
curl -s --max-time 120 -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"GLM-5.1","messages":[{"role":"user","content":"你好"}],"stream":true,"session_id":"test-stream"}'

# 6. 清理
kill %1  # 或 kill $(lsof -ti :8001)
```

**预期结果**: 步骤 4 返回 `"content":"你好"`（非空），步骤 5 返回 SSE 事件流。

## Key File Locations

| 用途 | 路径 |
|------|------|
| 签名缓存 (5min TTL) | `zaibot/zaibot_signature_cache.json` |
| 抓取的请求 (含 X-Signature) | `zaibot/captured_request.json` |
| Z.ai JWT token | `zaibot/zaibot_token.txt` |
| 浏览器状态 (cookies/session) | `zaibot/zaibot_state.json` |
| 账号数据库 | `zaibot-bridge/data/accounts.db` |
| 每账号浏览器数据 | `zaibot-bridge/data/accounts/<account>/state.json` |
| 服务日志 (手动启动时) | `/tmp/zaibot_server.log` |
