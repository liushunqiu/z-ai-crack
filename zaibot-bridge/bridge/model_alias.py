"""模型名映射。

将 Codex CLI 发送的模型名映射到 Z.ai 支持的模型。
支持从 Z.ai API 动态获取可用模型列表。
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Optional

# 模型别名映射:别名(小写) -> Z.ai 实际模型名
# 用于将 Codex CLI / OpenAI 客户端发送的模型名映射到 Z.ai 模型
MODEL_ALIASES: dict[str, str] = {
    # Codex 默认模型
    "gpt-5-codex": "GLM-5.1",
    "codex": "GLM-5.1",

    # OpenAI 模型名映射
    "gpt-4": "GLM-5.1",
    "gpt-4-turbo": "GLM-5.1",
    "gpt-4o": "GLM-5.1",
    "gpt-4o-mini": "GLM-5.1",
    "gpt-3.5-turbo": "GLM-5.1",
    "gpt-3.5": "GLM-5.1",

    # Claude 模型名映射
    "claude-3-opus": "GLM-5.1",
    "claude-3-sonnet": "GLM-5.1",
    "claude-3-haiku": "GLM-5.1",
    "claude-3.5-sonnet": "GLM-5.1",

    # Z.ai 原生模型名大小写映射 (API 返回小写，我们规范化为大写)
    "glm-5.1": "GLM-5.1",
    "glm-5-turbo": "GLM-5-Turbo",
    "glm-5v-turbo": "GLM-5v-Turbo",
    "glm-5": "GLM-5-Turbo",  # GLM-5 映射到 GLM-5-Turbo
    "glm-4.7": "GLM-4.7",
    "glm-4.6v": "GLM-4.6v",
    "glm-4.1v-thinking-flashx": "GLM-4.1V-Thinking-FlashX",
    "glm-4-flash": "glm-4-flash",
    "glm-4-air-250414": "glm-4-air-250414",
}

# 默认模型
DEFAULT_MODEL = "GLM-5.1"

# 模型列表缓存
_models_cache: Optional[list[str]] = None
_models_cache_time: float = 0
_CACHE_TTL = 3600  # 缓存 1 小时

# API 基础 URL
API_BASE = "https://chat.z.ai/api"


def _read_token() -> str:
    """读取 Z.ai token。"""
    import os
    from pathlib import Path

    # 尝试从 zaibot_state.json 读取
    state_file = Path(__file__).parent.parent.parent / "zaibot" / "zaibot_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            for origin in state.get("origins", []):
                if origin.get("origin") == "https://chat.z.ai":
                    for item in origin.get("localStorage", []):
                        if item.get("name") == "token":
                            return item.get("value", "")
        except Exception:
            pass

    # 尝试从 zaibot_token.txt 读取
    token_file = Path(__file__).parent.parent.parent / "zaibot" / "zaibot_token.txt"
    if token_file.exists():
        return token_file.read_text().strip()

    return ""


def _load_cookie_header() -> str:
    """从 zaibot_state.json 加载 cookie。"""
    from pathlib import Path

    state_file = Path(__file__).parent.parent.parent / "zaibot" / "zaibot_state.json"
    if not state_file.exists():
        return ""
    try:
        state = json.loads(state_file.read_text())
        pairs = []
        for c in state.get("cookies", []):
            domain = str(c.get("domain", "")).lstrip(".")
            if domain == "chat.z.ai" or domain.endswith(".chat.z.ai"):
                name = c.get("name")
                value = c.get("value")
                if name is not None and value is not None:
                    pairs.append(f"{name}={value}")
        return "; ".join(pairs)
    except Exception:
        return ""


def fetch_available_models() -> list[str]:
    """从 Z.ai API 获取可用模型列表。"""
    global _models_cache, _models_cache_time

    # 检查缓存
    if _models_cache and time.time() - _models_cache_time < _CACHE_TTL:
        return _models_cache

    token = _read_token()
    if not token:
        # 没有 token，返回默认模型
        return [DEFAULT_MODEL]

    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        cookie = _load_cookie_header()
        if cookie:
            headers["Cookie"] = cookie

        req = urllib.request.Request(f"{API_BASE}/models", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        models = [m["id"] for m in data.get("data", []) if m.get("id")]
        if models:
            _models_cache = models
            _models_cache_time = time.time()
            return models
    except Exception:
        pass

    # 获取失败，返回默认模型
    return [DEFAULT_MODEL]


def get_available_models() -> list[str]:
    """获取可用模型列表（带缓存）。"""
    return fetch_available_models()


def resolve_model(model: str | None) -> str:
    """解析模型名，返回 Z.ai 支持的模型名。

    解析顺序:
    1. 空值 -> 返回默认模型
    2. 精确匹配别名表
    3. 大小写不敏感匹配别名表
    4. 大小写不敏感匹配可用模型列表
    5. 前缀匹配 (如 GLM-5 -> GLM-5.1)
    6. 返回默认模型
    """
    if not model:
        return DEFAULT_MODEL

    model = model.strip()

    # 1. 精确匹配别名表
    lower = model.lower()
    if lower in MODEL_ALIASES:
        return MODEL_ALIASES[lower]

    # 2. 大小写不敏感匹配别名表
    for alias, target in MODEL_ALIASES.items():
        if alias.lower() == lower:
            return target

    # 3. 获取可用模型列表
    available = get_available_models()

    # 4. 大小写不敏感匹配可用模型
    for m in available:
        if m.lower() == lower:
            return m

    # 5. 前缀匹配 (如 GLM-5 -> GLM-5.1)
    for m in available:
        if m.lower().startswith(lower) or lower.startswith(m.lower()):
            return m

    # 6. 如果输入看起来像 Z.ai 模型名，直接返回
    if model.upper().startswith("GLM"):
        return model

    # 7. 默认返回第一个可用模型或默认模型
    return available[0] if available else DEFAULT_MODEL


def list_models_for_api() -> list[dict]:
    """生成 OpenAI 兼容的模型列表响应。"""
    available = get_available_models()
    return [
        {
            "id": m,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "z-ai",
        }
        for m in available
    ]
