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
