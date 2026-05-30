# Z.ai Bridge

OpenAI 兼容 API 代理，底层使用 Z.ai (chat.z.ai)。

## 快速开始

```bash
# 1. 先登录 Z.ai (获取 token)
cd ../zaibot
python3 login.py login

# 2. 启动 bridge 服务
cd ../zaibot-bridge
./start.sh
# 或者直接运行
python3 server.py
```

服务默认运行在 `http://localhost:8001`。

## API 端点

| 端点 | 方法 | 用途 |
|------|------|------|
| `/v1/chat/completions` | POST | OpenAI Chat Completions API |
| `/v1/responses` | POST | Codex Responses API |
| `/responses` | POST | Codex Responses API (无 /v1 前缀) |
| `/v1/models` | GET | 模型列表 |
| `/api/chat` | POST | 旧协议 (纯文本) |
| `/api/close` | POST | 关闭会话 |
| `/api/status` | GET | 服务状态 |

## 配置 Codex CLI

```bash
# 设置 OpenAI API base URL
export OPENAI_API_BASE=http://localhost:8001/v1

# 设置 API key (任意值，因为 Z.ai 使用自己的认证)
export OPENAI_API_KEY=sk-dummy

# 运行 codex
codex "你的提示"
```

## 支持的模型

- `GLM-5.1` (默认)
- `GLM-5`
- `GLM-4`

也可以使用别名：
- `gpt-5-codex` -> `GLM-5.1`
- `gpt-4` -> `GLM-5.1`
- `codex` -> `GLM-5.1`

## 会话管理

使用 `session_id` 保持会话连续性：

```bash
# 第一次请求
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "GLM-5.1",
    "messages": [{"role": "user", "content": "你好"}],
    "session_id": "my-session-123"
  }'

# 后续请求 (同一个 session_id)
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "GLM-5.1",
    "messages": [{"role": "user", "content": "继续"}],
    "session_id": "my-session-123"
  }'
```

## 工具调用 (DSML)

Z.ai 不原生支持 OpenAI 的 tools 字段，所以使用 DSML 协议将工具定义
注入到 prompt 中。模型会输出 DSML 格式的工具调用，bridge 会自动解析
并转换回 OpenAI 格式。

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ZAIBOT_HMAC_SECRET` | X-Signature HMAC 密钥 | 内置默认值 |

## 依赖

- Python 3.10+
- fastapi
- uvicorn
- pydantic

## 与 deepseek-bridge 的区别

| 维度 | zaibot-bridge | deepseek-bridge |
|------|---------------|-----------------|
| 目标平台 | chat.z.ai | chat.deepseek.com |
| 调用方式 | 纯 HTTP API | 浏览器桥接 |
| 签名/反爬 | X-Signature (已还原) | 无需签名 |
| Captcha | Camoufox 自动获取 | 无需 captcha |
| 端口 | 8001 | 8000 |
