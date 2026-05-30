# Z.ai 接口逆向项目状态

最后更新：2026-05-30

## 目标

通过 HTTP API 直接调用 `chat.z.ai` 的对话能力，尽量绕过完整浏览器自动化。

## 当前结论

- 登录态可以稳定保存和恢复。
- 对话 API 端点、请求参数、Header、SSE 响应格式已完全摸清。
- `X-Signature` 已本地还原（HMAC-SHA256），可纯本地生成签名。
- `captcha_verify_param` 已可通过 Camoufox 浏览器自动化获取，无需手动滑块。
- **支持同一会话连续发消息**（`ChatSession` 管理 chat_id 和消息链式引用）。
- **支持持久浏览器会话**（`CaptchaSession` 浏览器只启动一次，按需获取 token）。
- 当前最可用方案是：持久 Camoufox 浏览器 + 纯 HTTP 调用对话 API。

---

## 当前推荐使用方式

### 交互模式（推荐）

```bash
cd zaibot
../camoufox-reverse-mcp/.venv/bin/python zaibot_api.py
```

- 浏览器只启动一次，保持运行
- 每条消息自动获取新的 captcha token（新标签页，不影响浏览器状态）
- 所有消息在同一个聊天会话中（模型能记住上下文）
- Ctrl-D / Ctrl-C 退出时自动关闭浏览器

### 单条命令

```bash
# 新会话
../camoufox-reverse-mcp/.venv/bin/python zaibot_api.py "你的问题"

# 继续已有会话
../camoufox-reverse-mcp/.venv/bin/python zaibot_api.py --chat-id <uuid> "继续聊"
```

### 首次登录（只需一次）

```bash
../camoufox-reverse-mcp/.venv/bin/python login.py login
```

---

## 核心架构

```
zaibot_api.py (CLI 入口)
├── CaptchaSession (captcha_service.py)
│   ├── 浏览器只启动一次
│   ├── 每次 get_captcha() 开新标签页 → 获取 token → 关标签页
│   └── 浏览器上下文（cookies/storage）保持不变
│
├── ChatSession (zaibot_core.py)
│   ├── chat_id: 首次 post_chat 时创建，后续复用
│   ├── last_assistant_id: 上一条 assistant 消息 ID
│   └── 实现消息链式引用 (parent_id)
│
└── post_chat() (zaibot_core.py)
    ├── 本地生成 X-Signature (HMAC-SHA256)
    ├── 携带 captcha_verify_param
    ├── POST /api/v2/chat/completions
    └── 解析 SSE 响应 → 输出 phase=="answer" 内容
```

### 消息链式引用（同一会话）

```
消息1: chat_id=abc, id=uuid_1, parent_id=null       → create_chat()
消息2: chat_id=abc, id=uuid_2, parent_id=uuid_1     → 复用 chat_id
消息3: chat_id=abc, id=uuid_3, parent_id=uuid_2     → 复用 chat_id
```

### Captcha token 获取流程

```
浏览器上下文（保持存活）
├── 标签页1: chat.z.ai → 触发验证码 → 获取 token_1 → 关闭标签页
├── 标签页2: chat.z.ai → 触发验证码 → 获取 token_2 → 关闭标签页
└── 标签页3: chat.z.ai → 触发验证码 → 获取 token_3 → 关闭标签页
```

每个 token 一次性使用，每次 API 调用需要新的 token。

---

## 已实现模块

### 核心模块

| 文件 | 用途 | 状态 |
|------|------|------|
| `zaibot_core.py` | HTTP 核心：签名、请求构造、SSE 解析、`ChatSession` | **主力，可用** |
| `zaibot_api.py` | CLI 入口：交互/单条模式、captcha 自动获取、会话管理 | **主力，可用** |
| `captcha_service.py` | Camoufox 验证码服务：`CaptchaSession` 持久浏览器 + token 获取 | **主力，可用** |
| `login.py` | 登录、session 保存、token 恢复 | 可用 |

### 辅助工具

| 文件 | 用途 | 状态 |
|------|------|------|
| `sign.py` | 签名验证/回归测试 | 可用 |
| `capture_request.py` | 捕获真实请求 | 调试用 |
| `capture_signature.py` | 捕获真实签名 | 调试用 |
| `auto_captcha.py` | 真实 Chrome + CDP 验证码（备用） | 可用 |
| `get_captcha.py` | 手动滑块验证码（备用） | 可用 |

### 纯协议实验（未完成）

| 文件 | 用途 | 状态 |
|------|------|------|
| `captcha_protocol.js` | 纯 Node.js 验证码协议（InitCaptchaV3 已通，deviceToken 未完成） | 实验中 |
| `feilin_vm_probe.js` | FeiLin VM 沙箱探针（SG_WEB_PREID token 可生成，Log2 设备注册未通过） | 实验中 |
| `zaibot_client.py` | 封装式 API 客户端实验 | 半成品 |
| `signature_server.py` | 持久浏览器签名捕获服务 | 实验可用 |

### 已过时

| 文件 | 说明 |
|------|------|
| `api.py` / `api.js` | 早期原始客户端，缺签名/验证码 |
| `chat.py` / `chat_v2.py` | 早期浏览器方案，已被 `zaibot.py` 替代 |
| `extract_secret.py` | HMAC secret hook 实验，已解决 |
| `zaibot.py` | Camoufox DOM 自动化，备用方案 |

---

## API 请求结构

### 端点

```http
POST https://chat.z.ai/api/v2/chat/completions
```

### 必需 Header

```http
Authorization: Bearer <JWT token>
Content-Type: application/json
X-FE-Version: prod-fe-1.1.38
X-Region: overseas
X-Signature: <HMAC-SHA256 签名>
```

### Body 核心字段

```json
{
  "stream": true,
  "model": "GLM-5.1",
  "messages": [{"role": "user", "content": "prompt"}],
  "signature_prompt": "prompt",
  "chat_id": "<uuid>",
  "id": "<uuid>",
  "current_user_message_id": "<uuid>",
  "current_user_message_parent_id": "<上一条 assistant id 或 null>",
  "captcha_verify_param": "<base64 json>",
  "features": { "enable_thinking": false, ... },
  "background_tasks": { "title_generation": true, "tags_generation": true }
}
```

### SSE 响应

```text
data: {"data":{"phase":"answer","delta_content":"..."}}
data: [DONE]
```

---

## X-Signature 算法

```python
secret = "key-@@@@)))()((9))-xxxx&&&%%%%%"
bucket = str(int(timestamp // 300000))
key_hex = HMAC_SHA256(secret, bucket).hexdigest()
sorted_payload = "requestId,{rid},timestamp,{ts},user_id,{uid}"  # 按 key 字母序
message = f"{sorted_payload}|{base64(prompt)}|{timestamp}"
signature = HMAC_SHA256(key_hex, message).hexdigest()
```

---

## 验证码流程

### 当前方案（Camoufox 自动获取）

```text
Camoufox 浏览器
  → 导航 chat.z.ai
  → 输入消息 + 点击发送
  → 拦截 AliyunCaptcha 响应
  → 解析 certifyId + securityToken
  → base64({certifyId, sceneId:"didk33e0", isSign:true, securityToken})
```

### 验证码 token 特性

- 一次性使用，不能复用
- TTL 约几分钟
- 每次 API 调用都需要新的 token
- Camoufox TRACELESS 模式无需手动滑块

### 纯协议方案（未完成）

FeiLin `deviceToken` 纯协议生成是最后的瓶颈：
- `InitCaptchaV3` 已纯协议可调用
- `SG_WEB_PREID` token 格式已在 VM 中生成
- `Log2` 设备注册失败导致 `VerifyCaptchaV3` 返回 `F002`
- 详见 `feilin_vm_probe.js` 和下方历史记录

---

## 运行数据文件

| 文件 | 说明 |
|------|------|
| `zaibot_state.json` | 浏览器 storage state（cookies + localStorage） |
| `zaibot_token.txt` | JWT token |
| `zaibot_captcha_cache.json` | 验证码缓存（短 TTL） |
| `captured_request.json` | 捕获的真实请求样本 |

**注意**：这些文件包含账号凭证，不应提交到公开仓库。

---

## 快速接手 Checklist

1. `python3 login.py test` — 确认 token 有效
2. `python3 zaibot_api.py "hello"` — 确认主力方案能跑通
3. 如果失败，检查 `zaibot_state.json` 是否存在、token 是否过期
4. 如果验证码失败，Camoufox 可能需要重新启动（端口冲突等）
5. 如果签名失败，检查 `FE_VERSION` 是否需要更新

---

## 历史记录

<details>
<summary>2026-05-28 ~ 2026-05-29 开发历程（点击展开）

### 2026-05-28 X-Signature 还原

从 `prod-fe-1.1.37` 的 `nV()` 定位到签名算法，secret 为 `"key-@@@@)))()((9))-xxxx&&&%%%%%"`。

### 2026-05-28 验证码自动化

Camoufox 可成功完成 TRACELESS 验证码流程，无需手动滑块。

### 2026-05-28 纯协议验证码推进

`captcha_protocol.js` 已完成：
- Aliyun OpenAPI HMAC-SHA1 签名
- `Log1` 成功返回 `DeviceConfig`
- `InitCaptchaV3` 成功返回 `CertifyId`
- AES 双层加密

### 2026-05-29 FeiLin VM 沙箱

`feilin_vm_probe.js` 进展：
- `SG_WEB_PREID` token 可在 VM 中生成
- `sessionId` 绑定已解决
- Log2 设备注册仍是瓶颈（返回 `parameter formate error`）
- `VerifyCaptchaV3` 返回 `F002`

### 2026-05-29 Camoufox 验证码服务

发现新版 FeiLin 059 使用 TRACELESS 模式，Camoufox 可成功绕过。落地为 `captcha_service.py`。

### 2026-05-30 会话管理 + 持久浏览器

- `CaptchaSession`：持久浏览器，按需获取 token（新标签页）
- `ChatSession`：会话状态管理，支持同一会话连续发消息
- 交互模式默认同会话，模型能记住上下文
- 单条命令支持 `--chat-id` 继续已有会话
- `FE_VERSION` 更新到 `prod-fe-1.1.38`
</details>
