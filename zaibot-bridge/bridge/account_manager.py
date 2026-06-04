"""AccountManager: 多 Z.ai 账号管理 + session_id 粘性绑定 + round-robin 自动分配。

职责：
- 维护账号池 (每个账号 = 一个 CaptchaSession 浏览器 + 状态文件)
- session_id 首次出现时, 从 active 账号中按 round-robin 选一个绑定
- 同一 session_id 后续请求永远使用同一账号
- 启动时检查每个 active 账号, 验证 state 文件存在
- 提供 interactive_login 入口供 server.py 调用
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

# 加入 path 以便 import zaibot 的 captcha_service / zaibot_core
_BRIDGE_DIR = Path(__file__).parent.parent
ZAIBOT_DIR = _BRIDGE_DIR.parent / "zaibot"
sys.path.insert(0, str(ZAIBOT_DIR))

from captcha_service import CaptchaSession  # noqa: E402

from .db import Account, AccountDB, account_to_public_dict  # noqa: E402


class AccountManager:
    """多账号 + 粘性绑定 + round-robin。"""

    def __init__(self, db: AccountDB, *, data_dir: Path):
        self.db = db
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # account_id -> CaptchaSession (持久浏览器)
        self._sessions: dict[int, CaptchaSession] = {}
        self._session_lock = threading.Lock()
        # round-robin 游标
        self._rr_lock = threading.Lock()
        self._rr_cursor = 0
        # 启动时尝试为 active 账号恢复浏览器
        self._startup_init()

    def _account_dir(self, account_id: int) -> Path:
        d = self.data_dir / "accounts" / str(account_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _startup_init(self) -> None:
        """启动时检查所有 active 账号,如果 state 文件还在就保持 active。"""
        for acc in self.db.list_accounts():
            if acc.status == "active":
                state = Path(acc.storage_path)
                if not state.exists():
                    self.db.update_account(acc.id, status="error", note=f"state 文件丢失: {state}")
                    self.db.record_event("state_missing", account_id=acc.id, detail=str(state))

    # ---------- 账号管理 (admin API) ----------

    def list_accounts(self) -> list[dict]:
        return [account_to_public_dict(a) for a in self.db.list_accounts()]

    def create_account(self, name: str) -> dict:
        """创建新账号,返回账号信息和 storage 路径。"""
        existing = self.db.get_account_by_name(name)
        if existing:
            raise ValueError(f"账号名已存在: {name}")
        acc_dir = self.data_dir / "accounts" / name
        acc_dir.mkdir(parents=True, exist_ok=True)
        storage_path = str(acc_dir / "state.json")
        acc_id = self.db.add_account(name=name, storage_path=storage_path)
        self.db.record_event("account_created", account_id=acc_id, detail=name)
        return account_to_public_dict(self.db.get_account(acc_id))

    def delete_account(self, account_id: int) -> bool:
        """删除账号,关闭浏览器,清理绑定。"""
        acc = self.db.get_account(account_id)
        if not acc:
            return False
        self._close_session(account_id)
        # 删除 state 文件
        try:
            Path(acc.storage_path).unlink(missing_ok=True)
        except Exception:
            pass
        # 删除该账号的所有绑定
        with self._session_lock:
            for b in self.db.list_bindings_for_account(account_id):
                self.db.delete_binding(b.session_id)
        ok = self.db.delete_account(account_id)
        if ok:
            self.db.record_event("account_deleted", account_id=account_id, detail=acc.name)
        return ok

    def set_status(self, account_id: int, status: str) -> dict:
        if status not in {"pending_login", "active", "error", "disabled"}:
            raise ValueError(f"非法 status: {status}")
        acc = self.db.get_account(account_id)
        if not acc:
            raise ValueError(f"账号不存在: {account_id}")
        self.db.update_account(account_id, status=status)
        if status in {"disabled", "error"}:
            self._close_session(account_id)
        return account_to_public_dict(self.db.get_account(account_id))

    def rebind_session(self, session_id: str, account_id: int) -> dict:
        """管理员手动改绑 session_id 到新账号。"""
        acc = self.db.get_account(account_id)
        if not acc:
            raise ValueError(f"账号不存在: {account_id}")
        if acc.status not in {"active", "pending_login"}:
            raise ValueError(f"账号不可用 (status={acc.status})")
        self.db.set_binding(session_id, account_id)
        self.db.record_event(
            "session_rebound", account_id=account_id, session_id=session_id
        )
        return {"session_id": session_id, "account_id": account_id}

    def get_binding_info(self, session_id: str) -> Optional[dict]:
        b = self.db.get_binding(session_id)
        if not b:
            return None
        acc = self.db.get_account(b.account_id)
        return {
            "session_id": b.session_id,
            "account_id": b.account_id,
            "account_name": acc.name if acc else "",
            "account_status": acc.status if acc else "",
            "bound_at": b.bound_at,
            "last_active": b.last_active,
        }

    def list_bindings(self, *, limit: int = 200) -> list[dict]:
        out = []
        for b in self.db.list_bindings(limit=limit):
            acc = self.db.get_account(b.account_id)
            out.append({
                "session_id": b.session_id,
                "account_id": b.account_id,
                "account_name": acc.name if acc else "",
                "account_status": acc.status if acc else "",
                "bound_at": b.bound_at,
                "last_active": b.last_active,
            })
        return out

    def unbind_session(self, session_id: str) -> bool:
        ok = self.db.delete_binding(session_id)
        if ok:
            self.db.record_event("session_unbound", session_id=session_id)
        return ok

    # ---------- 交互登录 ----------

    def start_interactive_login(self, account_id: int, *, on_progress=None) -> bool:
        """为指定账号启动交互式登录流程 (headful 浏览器)。

        完成后保存 state 并将账号标记为 active。返回是否登录成功。
        """
        acc = self.db.get_account(account_id)
        if not acc:
            raise ValueError(f"账号不存在: {account_id}")
        state_path = Path(acc.storage_path)
        state_path.parent.mkdir(parents=True, exist_ok=True)

        # 先关闭该账号已有的浏览器
        self._close_session(account_id)

        # 启动新的 headful CaptchaSession 做登录
        login_session = CaptchaSession(
            headless=False,
            state_path=state_path,
        )
        # 跳过 state 加载 (state 可能不存在或已失效)
        # 我们手动 start 然后用 _context 直接 goto
        try:
            from camoufox import Camoufox
            with Camoufox(headless=False, geoip=False) as browser:
                context = browser.new_context()
                page = context.new_page()
                try:
                    if on_progress:
                        on_progress("opening_chat.z.ai")
                    page.goto("https://chat.z.ai/", wait_until="domcontentloaded", timeout=60000)
                    if on_progress:
                        on_progress("waiting_for_login")
                    deadline = time.time() + 300
                    while time.time() < deadline:
                        token = page.evaluate("() => localStorage.getItem('token') || ''")
                        token = (token or "").strip().strip('"')
                        if token:
                            user_raw = page.evaluate("() => localStorage.getItem('user') || ''")
                            if user_raw and user_raw != "null":
                                storage = context.storage_state()
                                state_path.write_text(
                                    __import__("json").dumps(storage, ensure_ascii=False, indent=2),
                                    encoding="utf-8",
                                )
                                user_id = ""
                                user_name = ""
                                try:
                                    parts = token.split(".")
                                    payload = __import__("json").loads(
                                        __import__("base64").urlsafe_b64decode(
                                            parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                                        )
                                    )
                                    user_id = payload.get("id", "")
                                    user = __import__("json").loads(user_raw)
                                    user_name = user.get("name", "")
                                except Exception:
                                    pass
                                self.db.update_account(
                                    account_id,
                                    status="active",
                                    user_id=user_id,
                                    user_name=user_name,
                                    last_login_at=time.time(),
                                )
                                if on_progress:
                                    on_progress("login_succeeded")
                                self.db.record_event(
                                    "login_success", account_id=account_id,
                                    detail=f"user_id={user_id}, user_name={user_name}",
                                )
                                return True
                        time.sleep(2)
                    if on_progress:
                        on_progress("login_timeout")
                    self.db.update_account(account_id, status="error", note="登录超时")
                    self.db.record_event("login_timeout", account_id=account_id)
                    return False
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
        except Exception as e:
            self.db.update_account(account_id, status="error", note=f"登录异常: {e}")
            self.db.record_event("login_failed", account_id=account_id, detail=str(e))
            if on_progress:
                on_progress(f"login_error: {e}")
            return False

    # ---------- 请求执行时的查找 ----------

    def resolve_account(self, session_id: Optional[str]) -> Optional[Account]:
        """根据 session_id 解析出要用的账号。

        - 若 session_id 已有绑定且账号 active: 返回该账号
        - 若 session_id 无绑定: 选一个 active 账号 (round-robin), 写入绑定
        - 若 session_id 绑定到非 active 账号: 重新分配

        返回 None 表示无可用账号。
        """
        if session_id:
            binding = self.db.get_binding(session_id)
            if binding:
                acc = self.db.get_account(binding.account_id)
                if acc and acc.status == "active":
                    self.db.touch_binding(session_id)
                    return acc
                # 绑定失效, 重新选
                self.db.delete_binding(session_id)
        # 新会话或旧绑定失效, 选一个 active 账号
        active = self.db.list_active_accounts()
        if not active:
            return None
        chosen = self._round_robin_pick(active)
        if session_id:
            self.db.set_binding(session_id, chosen.id)
            self.db.record_event(
                "session_bound", account_id=chosen.id, session_id=session_id,
                detail=chosen.name,
            )
        return chosen

    def _round_robin_pick(self, active: list[Account]) -> Account:
        """在 active 账号中按游标轮询选择, 然后让游标前进。"""
        with self._rr_lock:
            idx = self._rr_cursor % len(active)
            self._rr_cursor = (self._rr_cursor + 1) % len(active)
        return active[idx]

    # ---------- CaptchaSession 生命周期 ----------

    def get_captcha_session(self, account_id: int) -> CaptchaSession:
        """获取 (或懒创建) 该账号的 CaptchaSession。

        同一个账号共享一个浏览器实例, 不同账号独立。
        """
        with self._session_lock:
            sess = self._sessions.get(account_id)
            if sess is not None:
                return sess
            acc = self.db.get_account(account_id)
            if not acc:
                raise RuntimeError(f"账号不存在: {account_id}")
            if acc.status != "active":
                raise RuntimeError(f"账号 {acc.name} 不可用 (status={acc.status})")
            state_path = Path(acc.storage_path)
            if not state_path.exists():
                raise RuntimeError(f"账号 {acc.name} 缺少 state 文件: {state_path}")
            sess = CaptchaSession(
                headless=True,
                state_path=state_path,
            )
            sess.start()
            self._sessions[account_id] = sess
            return sess

    def _close_session(self, account_id: int) -> None:
        with self._session_lock:
            sess = self._sessions.pop(account_id, None)
        if sess:
            try:
                sess.close()
            except Exception:
                pass

    def close_all(self) -> None:
        with self._session_lock:
            ids = list(self._sessions.keys())
        for aid in ids:
            self._close_session(aid)

    def account_session_status(self) -> dict[int, str]:
        """返回每个账号的浏览器状态。"""
        with self._session_lock:
            return {aid: "running" for aid in self._sessions.keys()}

    def mark_request(self, account_id: int, *, success: bool) -> None:
        delta = 1 if success else 0
        err_delta = 0 if success else 1
        self.db.update_account(
            account_id,
            last_used_at=time.time(),
            request_count_delta=delta,
            error_count_delta=err_delta,
        )
