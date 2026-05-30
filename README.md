# z-ai-crack

Z.ai (chat.z.ai) API 逆向工程 + OpenAI 兼容 Bridge 服务。

通过纯 HTTP API 调用 Z.ai (GLM-5.1 / GLM-5 / GLM-4) 对话能力，提供 OpenAI Chat Completions 和 Codex Responses API 兼容接口，支持工具调用（DSML 协议）。

## 项目结构

```
z-ai-crack/
├── zaibot/                  # Z.ai 核心 API 客户端
│   ├── zaibot_core.py       # HTTP 核心：签名、请求构造、SSE 解析
│   ├── zaibot_api.py        # CLI 入口：交互/单条模式
│   ├── captcha_service.py   # Camoufox 验证码服务
│   ├── login.py             # 登录、session 保存
│   └── tools/               # 调试/分析工具
│
├── zaibot-bridge/           # OpenAI 兼容 Bridge 服务
│   ├── server.py            # FastAPI 主入口
│   └── bridge/
│       ├── runtime.py       # 请求执行引擎
│       ├── models.py        # 统一请求/事件模型
│       ├── dsml.py          # DSML 工具调用协议（渲染+解析）
│       ├── prompt_compat.py # Prompt 拍平层
│       ├── model_alias.py   # 模型名映射
│       └── adapters/
│           ├── chat.py      # OpenAI Chat Completions 适配器
│           └── responses.py # Codex Responses API 适配器
│
├── deepseek-bridge/         # DeepSeek Bridge（参考实现）
└── camoufox-reverse-mcp/    # Camoufox 反检测浏览器 MCP
```

## 快速开始

### 前置条件

- Python 3.10+
- Camoufox（验证码自动获取，随 `camoufox-reverse-mcp` 安装）

### 1. 登录 Z.ai（只需一次）

```bash
cd zaibot
../camoufox-reverse-mcp/.venv/bin/python login.py login
```

浏览器会打开 Z.ai 登录页，完成登录后自动保存 session。

### 2. 启动 Bridge 服务

**方式 A：一键启动（推荐）**

```bash
./start-zaibot-bridge.sh
```

自动检查登录状态、安装依赖、配置 Codex CLI、启动服务。

**方式 B：手动启动**

```bash
cd zaibot-bridge
pip install -r requirements.txt
python3 server.py
# 服务默认运行在 http://localhost:8001
```

### 3. 使用

**Codex CLI：**

```bash
export OPENAI_API_BASE=http://localhost:8001/v1
export OPENAI_API_KEY=sk-dummy
codex "你的提示"
```

**curl：**

```bash
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "GLM-5.1",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

**Z.ai CLI（不走 Bridge）：**

```bash
cd zaibot
../camoufox-reverse-mcp/.venv/bin/python zaibot_api.py "你的问题"
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/chat/completions` | POST | OpenAI Chat Completions API |
| `/v1/responses` | POST | Codex Responses API |
| `/responses` | POST | Codex Responses API（无 /v1 前缀） |
| `/v1/models` | GET | 模型列表 |
| `/api/chat` | POST | 旧协议（纯文本） |
| `/api/close` | POST | 关闭会话 |
| `/api/status` | GET | 服务状态 |

### 会话管理

使用 `session_id` 参数保持会话连续性，同一 `session_id` 的请求共享上下文：

```bash
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "GLM-5.1",
    "messages": [{"role": "user", "content": "记住我的名字是小明"}],
    "session_id": "my-session"
  }'

# 后续请求同 session_id
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "GLM-5.1",
    "messages": [{"role": "user", "content": "我叫什么？"}],
    "session_id": "my-session"
  }'
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

- 浏览器只启动一次，保持持久会话
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

## 已知限制

- 每次 API 调用需要新的 captcha token（一次性使用）
- `enable_thinking` 模式下 thinking 内容会作为 reasoning 返回
- 工具名/参数名大小写可能与 Codex 定义不一致（bridge 自动纠错）
- 纯协议验证码（无浏览器方案）尚在开发中，当前依赖 Camoufox 浏览器获取 captcha token
