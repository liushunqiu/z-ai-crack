#!/usr/bin/env python3
"""环境预检脚本: 在启动 bridge 前检查所有依赖项。

用法:
    cd zaibot-bridge && ../.venv/bin/python3 ../check_env.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BRIDGE = ROOT / "zaibot-bridge"
ZAIBOT = ROOT / "zaibot"

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

passed = 0
failed = 0
warnings = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        print(f"  {GREEN}✓{RESET} {name}")
        passed += 1
    else:
        print(f"  {RED}✗{RESET} {name}" + (f" — {detail}" if detail else ""))
        failed += 1


def warn(name: str, detail: str) -> None:
    global warnings
    print(f"  {YELLOW}⚠{RESET} {name} — {detail}")
    warnings += 1


def section(title: str) -> None:
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print(f"{'=' * 50}")


# ── 1. Python 版本 ──────────────────────────────────────────
section("Python 环境")
ver = sys.version_info
check(
    f"Python {ver.major}.{ver.minor}.{ver.micro}",
    ver >= (3, 10),
    f"需要 3.10+，当前 {ver.major}.{ver.minor}",
)
check("虚拟环境", sys.prefix != sys.base_prefix, "未检测到虚拟环境")

# ── 2. sys.path 配置 ────────────────────────────────────────
section("路径配置")
# 先确保路径在 sys.path 中
for p in [str(BRIDGE), str(ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

def _path_in_syspath(target: Path) -> bool:
    resolved = str(target.resolve())
    return any(str(Path(p).resolve()) == resolved for p in sys.path if p)

bridge_in_path = _path_in_syspath(BRIDGE)
root_in_path = _path_in_syspath(ROOT)
check("bridge 目录在 sys.path", bridge_in_path)
check("项目根目录在 sys.path", root_in_path)

# ── 3. 核心依赖 ─────────────────────────────────────────────
section("核心依赖")
deps = [
    ("fastapi", "FastAPI 框架"),
    ("uvicorn", "ASGI 服务器"),
    ("pydantic", "数据验证"),
    ("playwright", "浏览器自动化 (Camoufox)"),
]
for mod, desc in deps:
    try:
        importlib.import_module(mod)
        check(f"{mod} ({desc})", True)
    except ImportError as e:
        check(f"{mod} ({desc})", False, str(e))

# ── 4. 项目模块导入 ─────────────────────────────────────────
section("项目模块导入")

modules = [
    ("zaibot.zaibot_core", "Z.ai 核心 (签名/请求)"),
    ("zaibot.captcha_service", "Captcha 服务"),
    ("bridge.runtime", "请求运行时"),
    ("bridge.account_manager", "账号管理"),
    ("bridge.config", "配置"),
    ("bridge.adapters.chat", "Chat 适配器"),
    ("bridge.adapters.responses", "Responses 适配器"),
]
for mod, desc in modules:
    try:
        importlib.import_module(mod)
        check(f"{mod}", True)
    except Exception as e:
        check(f"{mod}", False, f"{type(e).__name__}: {e}")

# 额外检查: pathlib.Path 和 queue (历史 bug)
section("关键标准库导入")
try:
    from pathlib import Path as _Path
    check("pathlib.Path", True)
except ImportError as e:
    check("pathlib.Path", False, str(e))

try:
    import queue as _queue
    check("queue", True)
except ImportError as e:
    check("queue", False, str(e))

# ── 5. Token / 签名状态 ────────────────────────────────────
section("认证状态")

token_file = ZAIBOT / "zaibot_token.txt"
state_file = ZAIBOT / "zaibot_state.json"
cache_file = ZAIBOT / "zaibot_signature_cache.json"
captured_file = ZAIBOT / "captured_request.json"

check("zaibot_token.txt 存在", token_file.exists())
check("zaibot_state.json 存在", state_file.exists())

# 签名状态
hmac_secret = os.environ.get("ZAIBOT_HMAC_SECRET", "").strip()
if hmac_secret:
    check("ZAIBOT_HMAC_SECRET 已设置", True)
else:
    warn("ZAIBOT_HMAC_SECRET 未设置", "将使用 captured_request.json fallback")

if cache_file.exists():
    try:
        data = json.loads(cache_file.read_text())
        age = time.time() - data.get("created_at", 0)
        ok = age < 300
        check(f"签名缓存 ({age:.0f}s)", ok, f"已过期 ({age:.0f}s > 300s)" if not ok else "")
    except Exception as e:
        check("签名缓存", False, str(e))
else:
    warn("签名缓存不存在", "将回退到 captured_request.json")

if captured_file.exists():
    try:
        data = json.loads(captured_file.read_text())
        reqs = data.get("requests", [])
        latest = reqs[-1] if reqs else {}
        ts = latest.get("timestamp", 0)
        # captured_request.json 使用毫秒时间戳
        ts_sec = ts / 1000 if ts > 1e12 else ts
        age = time.time() - ts_sec if ts else float("inf")
        check(
            f"captured_request.json ({len(reqs)} 条, 最新 {age:.0f}s 前)",
            len(reqs) > 0,
        )
    except Exception as e:
        check("captured_request.json", False, str(e))
else:
    check("captured_request.json", False, "文件不存在且无 HMAC_SECRET")

# ── 6. 账号数据库 ──────────────────────────────────────────
section("账号数据库")
db_file = BRIDGE / "data" / "accounts.db"
check("accounts.db 存在", db_file.exists())
if db_file.exists():
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM accounts WHERE status='active'")
        active = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM accounts")
        total = cur.fetchone()[0]
        conn.close()
        check(f"活跃账号: {active}/{total}", active > 0, "没有活跃账号")
    except Exception as e:
        check("账号数据库查询", False, str(e))

# ── 7. 端口状态 ────────────────────────────────────────────
section("端口状态")
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
port_free = sock.connect_ex(("127.0.0.1", 8001)) != 0
sock.close()
check("端口 8001 可用", port_free, "端口被占用，需先 kill 旧进程")

# ── 汇总 ───────────────────────────────────────────────────
print(f"\n{'─' * 50}")
total = passed + failed
status_color = GREEN if failed == 0 else RED
print(f"  结果: {status_color}{passed}/{total} 通过{RESET}" + (f", {YELLOW}{warnings} 警告{RESET}" if warnings else ""))
if failed > 0:
    print(f"  {RED}有 {failed} 项检查失败，请修复后再启动服务{RESET}")
    sys.exit(1)
elif warnings > 0:
    print(f"  {YELLOW}有 {warnings} 项警告，服务可能部分功能受限{RESET}")
    sys.exit(0)
else:
    print(f"  {GREEN}所有检查通过，可以启动服务{RESET}")
    sys.exit(0)
