# z-ai-crack

Z.ai (chat.z.ai) API 逆向工程 + OpenAI 兼容 Bridge 服务，支持**多账号粘性绑定**与 **Web 管理界面**。

通过纯 HTTP API 调用 Z.ai (GLM-5.1 / GLM-5 / GLM-4) 对话能力，提供 OpenAI Chat Completions 和 Codex Responses API 兼容接口，支持工具调用（DSML 协议）。多账号场景下，同一 `session_id` 永远使用同一 Z.ai 账号，新 `session_id` 自动 round-robin 分配。

## 项目结构

```
z-ai-crack/
├── zaibot/                      # Z.ai 核心 API 客户端
│   ├── zaibot_core.py           # HTTP 核心：签名、请求构造、SSE 解析
│   ├── zaibot_api.py            # CLI 入口：交互/单条模式
│   ├── captcha_service.py       # Camoufox 验证码服务 (CaptchaSession + interactive_login)
│   ├── login.py                 # 登录、session 保存
│   └── tools/                   # 调试/分析工具
│
├── zaibot-bridge/               # OpenAI 兼容 Bridge 服务
│   ├── server.py                # FastAPI 主入口 + /admin 路由
│   ├── static/
│   │   └── admin.html           # Web 管理界面 (单页)
│   ├── data/                    # 运行时数据 (accounts.db + per-account state)
│   └── bridge/
│       ├── runtime.py           # 请求执行引擎 (多账号感知)
│       ├── db.py                # SQLite 持久化 (accounts / bindings / events)
│       ├── account_manager.py   # 多账号 + round-robin + 粘性绑定
│       ├── session_cache.py     # TTL + LRU 会话缓存
│       ├── models.py            # 统一请求/事件模型
│       ├── dsml.py              # DSML 工具调用协议 (渲染+解析)
│       ├── prompt_compat.py     # Prompt 拍平层
│       ├── model_alias.py       # 模型名映射
│       └── adapters/
│           ├── chat.py          # OpenAI Chat Completions 适配器
│           └── responses.py     # Codex Responses API 适配器
│
└── camoufox-reverse-mcp/        # Camoufox 反检测浏览器 MCP
```

## 快速开始

### 前置条件

- Python 3.10+
- Camoufox（验证码自动获取，随 `camoufox-reverse-mcp` 安装）

### 1. 启动 Bridge

```bash
cd zaibot-bridge
pip install -r requirements.txt
python3 server.py
# 服务默认运行在 http://localhost:8001
# 管理界面: http://localhost:8001/admin
```

### 2. 添加并登录 Z.ai 账号

打开浏览器访问 `http://localhost:8001/admin`：

1. 在「账号列表」输入账号名（如 `alice`），点「+ 添加账号」
2. 在新行点「登录」→ 弹出 Camoufox 浏览器窗口
3. 在弹出的浏览器中**手动完成 Z.ai 登录**（扫码 / 邮箱 / 密码均可）
4. 登录成功后状态自动变为 `active`
5. 重复以上步骤添加更多账号（`bob`、`charlie` …）

### 3. 调用 API

> **粘性绑定规则**：同一 `session_id` 永远路由到同一账号；新 `session_id` 自动 round-robin 分配到下一个 `active` 账号。

**curl：**

```bash
# 这个 session_id 会绑到 alice（或下一个可用账号）
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "GLM-5.1",
    "messages": [{"role": "user", "content": "记住我的名字是小明"}],
    "session_id": "user-1"
  }'

# 不同的 session_id 会绑到不同账号
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "GLM-5.1",
    "messages": [{"role": "user", "content": "你好"}],
    "session_id": "user-2"
  }'

# 相同 session_id 后续请求保持绑定
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "GLM-5.1",
    "messages": [{"role": "user", "content": "我叫什么?"}],
    "session_id": "user-1"
  }'
```

**Codex CLI：**

```bash
export OPENAI_API_BASE=http://localhost:8001/v1
export OPENAI_API_KEY=sk-dummy
codex --session-id "user-1" "你的提示"
```

**Z.ai CLI（不走 Bridge，单账号本地直连）：**

```bash
cd zaibot
../camoufox-reverse-mcp/.venv/bin/python login.py login   # 首次登录
../camoufox-reverse-mcp/.venv/bin/python zaibot_api.py "你的问题"
```

## API 端点

### 业务接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/chat/completions` | POST | OpenAI Chat Completions API |
| `/v1/responses` | POST | Codex Responses API |
| `/responses` | POST | Codex Responses API（无 `/v1` 前缀） |
| `/v1/models` | GET | 模型列表 |
| `/api/chat` | POST | 旧协议（纯文本） |
| `/api/close` | POST | 关闭会话 |
| `/api/status` | GET | 服务状态 |

### 管理接口（`/admin`）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/admin` | GET | Web 管理界面（HTML） |
| `/admin/api/accounts` | GET / POST | 列出 / 创建账号 |
| `/admin/api/accounts/{id}` | PATCH / DELETE | 修改状态（启停） / 删除 |
| `/admin/api/accounts/{id}/login` | POST | 触发 headful 登录（SSE 进度推送） |
| `/admin/api/bindings` | GET | 列出所有会话绑定 |
| `/admin/api/bindings/{sid}` | GET / PATCH / DELETE | 查询 / 改绑 / 解绑会话 |
| `/admin/api/resolve` | GET | 预览：某 session_id 会绑到哪个账号 |
| `/admin/api/events` | GET | 事件流水（登录、绑定、错误等） |

### 会话与账号绑定

```bash
# 查看 user-1 绑到了哪个账号
curl "http://localhost:8001/admin/api/bindings/user-1"

# 管理员改绑 user-1 到账号 2
curl -X PATCH http://localhost:8001/admin/api/bindings/user-1 \
  -H "Content-Type: application/json" \
  -d '{"account_id": 2}'

# 解绑（下次请求会重新分配）
curl -X DELETE http://localhost:8001/admin/api/bindings/user-1
```

## 多账号架构

### 数据流

```
HTTP 请求 (带 session_id)
  │
  ▼
ChatRuntimeService.execute()
  │
  ▼
AccountManager.resolve_account(session_id)
  │  ├─ 已有绑定 & 账号 active ──→ 复用
  │  └─ 无绑定 / 绑定失效       ──→ round-robin 选 active 账号
  │
  ▼
该账号的 CaptchaSession (独立 Camoufox 浏览器) ──→ captcha token
  │
  ▼
urllib + 该账号的 token/cookie ──→ Z.ai /api/v2/chat/completions
  │
  ▼
SSE 流式响应 → 解析 → 产出 OpenAI 事件
```

### 粘性绑定示例

```
账号池: alice (active), bob (active), charlie (active)

session_id=user-1  ──→  alice     (round-robin 起始)
session_id=user-2  ──→  bob
session_id=user-3  ──→  charlie
session_id=user-1  ──→  alice     (复用)
session_id=user-2  ──→  bob       (复用)
```

管理员通过 `/admin` 可随时查看、改绑、停用账号。

### 状态机

```
pending_login ──(登录成功)──→ active ──(停用)──→ disabled
     ↑                          │                     │
     │                          └──(token 失效)──→ error
     └──────────────(重新登录)─────────────────────┘
```

## 核心技术

### X-Signature 还原

Z.ai 使用 HMAC-SHA256 签名防重放，已从 `prod-fe-1.1.37` 的 `nV()` 完全还原：

```python
secret = "key-@@@@)))()((9))-xxxx&&&%%%%%"
bucket = str(int(timestamp // 300000))
key_hex = HMAC_SHA256(secret, bucket).hexdigest()
sorted_payload = "requestId,{rid},timestamp,{ts},user_id,{uid}"  # 按 key 字母序
message = f"{sorted_payload}|{base64(prompt)}|{timestamp}"
signature = HMAC_SHA256(key_hex, message).hexdigest()
```

### Captcha 自动获取

通过 Camoufox 反检测浏览器自动完成 AliyunCaptcha (TRACELESS 模式) 验证：

- **单账号场景**：浏览器只启动一次，保持持久会话
- **多账号场景**：每账号一个独立 Camoufox 浏览器实例
- 每次 API 调用开新标签页获取 token，不影响浏览器状态
- Token 一次性使用，TTL 约几分钟

### DSML 工具调用协议

Z.ai 不原生支持 OpenAI `tools` 字段，使用 DSML 协议将工具定义注入 prompt：

```xml
<|DSML|tool_calls>
  <|DSML|invoke name="Bash">
    <|DSML|parameter name="command"><![CDATA[ls -la]]></|DSML|parameter>
  </|DSML|invoke>
</|DSML|tool_calls>
```

Bridge 自动完成双向转换：
- **入站**：OpenAI `tools` 数组 → DSML 文本注入 prompt
- **出站**：Z.ai 返回的 DSML 文本 → OpenAI `function_call` 事件

### 工具调用完整流程

```
Codex CLI                    Bridge                     Z.ai
   |                            |                         |
   |-- POST /v1/responses ----->|                         |
   |   (tools + messages)       |-- POST /api/v2/ ------>|
   |                            |   (DSML 工具定义注入)    |
   |                            |                         |
   |                            |<-- SSE (DSML tool call)-|
   |<-- function_call event ----|   (解析 DSML → 事件)    |
   |                            |                         |
   |-- function_call_output --->|                         |
   |   (工具执行结果)            |-- POST /api/v2/ ------>|
   |                            |   (工具结果作为消息)      |
   |                            |                         |
   |                            |<-- SSE (最终回答) -------|
   |<-- text delta events ------|                         |
```

## 支持的模型

| Z.ai 模型 | 别名 |
|-----------|------|
| GLM-5.1（默认） | gpt-5-codex, codex, gpt-4 |
| GLM-5-Turbo | GLM-5, glm-5 |
| GLM-4.7 | glm-4.7 |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ZAIBOT_HMAC_SECRET` | X-Signature HMAC 密钥 | 内置默认值 |

## 持久化数据

所有运行时数据存放在 `zaibot-bridge/data/`（已加入 `.gitignore`）：

```
data/
├── accounts.db              # SQLite: 账号 + 绑定 + 事件
└── accounts/
    ├── alice/
    │   └── state.json       # Playwright storage_state (cookies + localStorage)
    ├── bob/
    │   └── state.json
    └── charlie/
        └── state.json
```

> ⚠️ `state.json` 含登录态 cookies + JWT token，**不要提交到公开仓库**。

## 已知限制

- 每次 API 调用需要新的 captcha token（一次性使用）
- `enable_thinking` 模式下 thinking 内容会作为 reasoning 返回
- 工具名/参数名大小写可能与 Codex 定义不一致（bridge 自动纠错）
- 纯协议验证码（无浏览器方案）尚在开发中，当前依赖 Camoufox 浏览器获取 captcha token
- 多个 Camoufox 浏览器实例较占内存（每个约 200-500MB），账号数建议 ≤ 5
- 改绑会话会导致该会话的 `chat_id` 在下次请求时被重置（开始新对话）

## 故障排查

| 现象 | 排查 |
|------|------|
| `/admin/api/accounts` 为空 | 没添加账号 → 在 UI 点「+ 添加账号」 |
| 登录卡住不动 | 检查 Camoufox 浏览器是否被其他程序占用；尝试删除账号重建 |
| 账号 `error` 状态 | token 过期 → 点「启用」后重新「登录」 |
| 请求报 `401` / `未授权` | 该账号的 cookie 失效 → 在 UI 重新登录 |
| 浏览器无窗口弹出 | headful 模式在无桌面环境会失败，需要 X11/SSH 图形转发 |
| 某个 session_id 总是报错 | 在 UI 看它绑到哪个账号，可能是该账号失效；用「改绑」换到别的账号 |
