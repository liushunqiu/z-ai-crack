"""Centralized configuration for zaibot-bridge.

All tunable constants live here instead of being scattered across modules.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Target platform
# ---------------------------------------------------------------------------
API_BASE = "https://chat.z.ai/api"
CHAT_DOMAIN = "https://chat.z.ai"

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
DEFAULT_HOST = os.environ.get("ZAIBOT_HOST", "127.0.0.1")
DEFAULT_PORT = 8001

# ---------------------------------------------------------------------------
# Session cache
# ---------------------------------------------------------------------------
SESSION_MAX_SIZE = 256
SESSION_TTL_SECONDS = 1800.0

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
MIN_REQUEST_INTERVAL = 2.0          # per-account
GLOBAL_MIN_INTERVAL = 1.0           # across all accounts
MAX_CONCURRENT_CAPTCHAS = 2         # per-account captcha browsers
LOGIN_TIMEOUT_SECONDS = 900         # 15 minutes

# ---------------------------------------------------------------------------
# Captcha / browser
# ---------------------------------------------------------------------------
CAPTCHA_SCENE_ID = "didk33e0"
CAPTCHA_TIMEOUT_MS = 10_000
BROWSER_NAV_TIMEOUT_MS = 90_000

# ---------------------------------------------------------------------------
# HTTP / API
# ---------------------------------------------------------------------------
HTTP_TIMEOUT_SECONDS = 60.0
STREAM_CHUNK_SIZE = 1024

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
USE_PURE_HTTP = os.environ.get("ZAIBOT_USE_PURE_HTTP", "").lower() in ("1", "true", "yes")
