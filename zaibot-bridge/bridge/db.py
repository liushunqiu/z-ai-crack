"""SQLite 持久化层：账号、会话绑定、事件日志。

数据模型：
- accounts: 账号元信息 + 状态 + 统计
- session_bindings: session_id -> account_id (粘性绑定)
- events: 账号/会话事件流水 (登录、错误、绑定、请求等)
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    storage_path    TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending_login',
    user_id         TEXT    DEFAULT '',
    user_name       TEXT    DEFAULT '',
    note            TEXT    DEFAULT '',
    last_used_at    REAL    DEFAULT 0,
    last_login_at   REAL    DEFAULT 0,
    request_count   INTEGER DEFAULT 0,
    error_count     INTEGER DEFAULT 0,
    created_at      REAL    NOT NULL,
    updated_at      REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status);

CREATE TABLE IF NOT EXISTS session_bindings (
    session_id      TEXT    PRIMARY KEY,
    account_id      INTEGER NOT NULL,
    bound_at        REAL    NOT NULL,
    last_active     REAL    NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bindings_account ON session_bindings(account_id);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER,
    session_id      TEXT,
    event_type      TEXT    NOT NULL,
    detail          TEXT    DEFAULT '',
    created_at      REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_account ON events(account_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, created_at);
"""


ACCOUNT_STATUSES = {"pending_login", "active", "error", "disabled"}


@dataclass
class Account:
    id: int
    name: str
    storage_path: str
    status: str
    user_id: str
    user_name: str
    note: str
    last_used_at: float
    last_login_at: float
    request_count: int
    error_count: int
    created_at: float
    updated_at: float

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Account":
        return cls(**{k: row[k] for k in row.keys()})


@dataclass
class SessionBinding:
    session_id: str
    account_id: int
    bound_at: float
    last_active: float

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SessionBinding":
        return cls(**{k: row[k] for k in row.keys()})


class AccountDB:
    """线程安全的 SQLite 包装。所有方法内部加锁。"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # check_same_thread=False 允许多线程共享连接；我们靠 _lock 串行化
        self._conn = sqlite3.connect(
            str(db_path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------- accounts ----------

    def add_account(self, *, name: str, storage_path: str) -> int:
        """创建新账号,初始状态 pending_login。返回 id。"""
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO accounts (name, storage_path, status, created_at, updated_at)
                   VALUES (?, ?, 'pending_login', ?, ?)""",
                (name, storage_path, now, now),
            )
            return cur.lastrowid

    def get_account(self, account_id: int) -> Optional[Account]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM accounts WHERE id=?", (account_id,)
            ).fetchone()
            return Account.from_row(row) if row else None

    def get_account_by_name(self, name: str) -> Optional[Account]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM accounts WHERE name=?", (name,)
            ).fetchone()
            return Account.from_row(row) if row else None

    def list_accounts(self) -> list[Account]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM accounts ORDER BY id ASC"
            ).fetchall()
            return [Account.from_row(r) for r in rows]

    def list_active_accounts(self) -> list[Account]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM accounts WHERE status='active' ORDER BY id ASC"
            ).fetchall()
            return [Account.from_row(r) for r in rows]

    def update_account(
        self,
        account_id: int,
        *,
        status: Optional[str] = None,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        note: Optional[str] = None,
        last_used_at: Optional[float] = None,
        last_login_at: Optional[float] = None,
        request_count_delta: Optional[int] = None,
        error_count_delta: Optional[int] = None,
    ) -> None:
        sets: list[str] = []
        vals: list[Any] = []
        if status is not None:
            sets.append("status=?"); vals.append(status)
        if user_id is not None:
            sets.append("user_id=?"); vals.append(user_id)
        if user_name is not None:
            sets.append("user_name=?"); vals.append(user_name)
        if note is not None:
            sets.append("note=?"); vals.append(note)
        if last_used_at is not None:
            sets.append("last_used_at=?"); vals.append(last_used_at)
        if last_login_at is not None:
            sets.append("last_login_at=?"); vals.append(last_login_at)
        if request_count_delta is not None:
            sets.append("request_count=request_count+?"); vals.append(request_count_delta)
        if error_count_delta is not None:
            sets.append("error_count=error_count+?"); vals.append(error_count_delta)
        if not sets:
            return
        sets.append("updated_at=?"); vals.append(time.time())
        vals.append(account_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE accounts SET {', '.join(sets)} WHERE id=?", vals
            )

    def delete_account(self, account_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM accounts WHERE id=?", (account_id,)
            )
            return cur.rowcount > 0

    # ---------- bindings ----------

    def get_binding(self, session_id: str) -> Optional[SessionBinding]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM session_bindings WHERE session_id=?", (session_id,)
            ).fetchone()
            return SessionBinding.from_row(row) if row else None

    def set_binding(self, session_id: str, account_id: int) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO session_bindings (session_id, account_id, bound_at, last_active)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       account_id=excluded.account_id,
                       bound_at=excluded.bound_at,
                       last_active=excluded.last_active""",
                (session_id, account_id, now, now),
            )

    def touch_binding(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE session_bindings SET last_active=? WHERE session_id=?",
                (time.time(), session_id),
            )

    def list_bindings(self, *, limit: int = 200) -> list[SessionBinding]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM session_bindings ORDER BY last_active DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [SessionBinding.from_row(r) for r in rows]

    def list_bindings_for_account(self, account_id: int) -> list[SessionBinding]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM session_bindings WHERE account_id=? ORDER BY last_active DESC",
                (account_id,),
            ).fetchall()
            return [SessionBinding.from_row(r) for r in rows]

    def delete_binding(self, session_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM session_bindings WHERE session_id=?", (session_id,)
            )
            return cur.rowcount > 0

    def count_bindings_for_account(self, account_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM session_bindings WHERE account_id=?",
                (account_id,),
            ).fetchone()
            return int(row["n"]) if row else 0

    # ---------- events ----------

    def record_event(
        self,
        event_type: str,
        *,
        account_id: Optional[int] = None,
        session_id: Optional[str] = None,
        detail: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO events (account_id, session_id, event_type, detail, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (account_id, session_id, event_type, detail, time.time()),
            )

    def list_events(self, *, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT e.id, e.account_id, e.session_id, e.event_type, e.detail, e.created_at,
                          a.name AS account_name
                   FROM events e
                   LEFT JOIN accounts a ON a.id = e.account_id
                   ORDER BY e.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]


def account_to_public_dict(acc: Account) -> dict:
    """账号信息转字典 (供 API 返回)。"""
    return {
        "id": acc.id,
        "name": acc.name,
        "status": acc.status,
        "user_id": acc.user_id,
        "user_name": acc.user_name,
        "note": acc.note,
        "last_used_at": acc.last_used_at,
        "last_login_at": acc.last_login_at,
        "request_count": acc.request_count,
        "error_count": acc.error_count,
        "created_at": acc.created_at,
        "updated_at": acc.updated_at,
    }
