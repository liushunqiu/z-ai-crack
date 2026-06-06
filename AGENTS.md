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
- **Pure HTTP vs DOM Fetch**: 默认 DOM Fetch 路径在无代理时可用。但使用代理时，**必须用 Pure HTTP + SOCKS5**（`ZAIBOT_USE_PURE_HTTP=1` + `ZAIBOT_PROXY=socks5://...`），让 urllib 和 Camoufox 浏览器从同一代理 IP 出去，否则 captcha 指纹绑定不匹配。DOM Fetch 路径下浏览器 `__nativeFetch` 会被 Aliyun WAF 拦截（405）。

## 风控规避策略（实测验证）

### Z.ai 风控层级

| 层级 | 触发条件 | 后果 | 恢复方式 |
|------|---------|------|---------|
| Captcha 质量 | Aliyun 行为评分低 | `FRONTEND_CAPTCHA_REQUIRED` | 等 30s+ 重试 |
| IP 级 WAF | 短时间内多次 captcha 失败 | HTTP 405 (Aliyun WAF 页面) | 换 IP 或等数小时 |
| 账号冷却 | 单账号触发 WAF | 该账号 30min 不可用 | 等待自动恢复 |
| 全局 IP 冷却 | 任一账号触发 WAF | 所有账号 30min 暂停 | 重启服务清内存 + 等 DB 冷却过期 |
| 账号自动禁用 | 1h 内 3+ 限流错误 | 账号永久 disabled | 手动重新登录 |

### 实测数据（2026-06-06）

**测试 A: 无代理 + DOM Fetch（失败）**

连续对话，单账号，15s 间隔：

| 轮次 | 耗时 | 结果 | 备注 |
|------|------|------|------|
| 1 | 14.3s | OK | 首轮创建 chat_id |
| 2 | 22.2s | OK | captcha 重试 1 次 |
| 3 | 9.6s | OK | 一次通过 |
| 4 | 35.8s | 失败 | WAF 405 → 30min IP 冷却 |

**测试 B: Pure HTTP + SOCKS5 代理（成功）**

```bash
ZAIBOT_USE_PURE_HTTP=1 ZAIBOT_PROXY=socks5://127.0.0.1:33211 python3 server.py
```

| 轮次 | 耗时 | 结果 | 备注 |
|------|------|------|------|
| 1 | 24.0s | OK | 首轮创建 chat_id |
| 2 | 10.7s | OK | 记忆验证：正确回答「小明」 |
| 3 | 33.3s | OK | 记忆验证：正确回答「火锅」 |
| 4 | 15.7s | OK | 长文本：火锅诗 |
| 5 | 23.9s | OK | 完整对话总结 |

**结论**: 无代理时单账号约 3 次后 WAF 拦截。使用 Pure HTTP + SOCKS5 代理可稳定 5+ 轮对话，零 WAF 错误。

### 推荐配置

**最佳方案（Pure HTTP + SOCKS5 代理）：**
```bash
cd zaibot-bridge
ZAIBOT_USE_PURE_HTTP=1 ZAIBOT_PROXY=socks5://127.0.0.1:你的SOCKS5端口 ../.venv/bin/python3 server.py
```
- Camoufox 浏览器走 SOCKS5 代理获取 captcha（geoip=True 自动匹配指纹）
- urllib 通过 pysocks 全局走同一 SOCKS5 代理
- 所有请求从同一代理 IP 出去，captcha 指纹绑定匹配
- 需要安装: `pip install pysocks` 和 `pip install camoufox[geoip]`

**无代理场景（仅限低频率使用）：**
- 请求间隔 ≥ 30 秒
- 每小时不超过 10 次请求
- 使用默认 DOM Fetch 路径（不设置 `ZAIBOT_USE_PURE_HTTP`）

**多账号场景（推荐 ≥ 3 个账号 + 代理）：**
- 每账号间隔 ≥ 30 秒
- 全局间隔 ≥ 10 秒（不同账号轮换）
- 每账号绑定不同代理出口 IP

**已实现的自动保护：**
- `verify_failed` 退避：30s → 90s（`runtime.py`，修复前为 5s → 10s）
- Captcha 最小间隔：6s（`captcha_service.py`，修复前为 4s）
- 全局请求间隔：1s（`config.py:GLOBAL_MIN_INTERVAL`）
- 单账号请求间隔：2s（`config.py:MIN_REQUEST_INTERVAL`）
- 集群故障检测：60s 内半数账号失败 → 30min 全局冷却

### 被 IP 封禁后的恢复步骤

1. 等待数小时（Aliyun WAF 通常 1-4 小时自动解除）
2. 或切换到代理 IP
3. 重启服务清除内存中的冷却状态
4. 清除 DB 中的账号冷却：
```bash
sqlite3 zaibot-bridge/data/accounts.db "UPDATE accounts SET status='active', cooldown_until=0 WHERE status='cooldown';"
```
5. 用更长间隔重新测试

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

# 2. 启动服务 (默认使用 DOM Fetch 路径)
../.venv/bin/python3 server.py &
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
