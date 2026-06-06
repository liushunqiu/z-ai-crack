from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from bridge.db import AccountDB, Account


class TestAccountDB:
    @pytest.fixture
    def db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        db = AccountDB(path)
        yield db
        path.unlink(missing_ok=True)

    def test_create_account(self, db: AccountDB):
        acc_id = db.add_account(name="alice", storage_path="/tmp/alice")
        assert acc_id is not None
        acc = db.get_account(acc_id)
        assert acc is not None
        assert acc.name == "alice"
        assert acc.status == "pending_login"

    def test_create_duplicate_name(self, db: AccountDB):
        import sqlite3
        db.add_account(name="alice", storage_path="/tmp/alice")
        with pytest.raises(sqlite3.IntegrityError):
            db.add_account(name="alice", storage_path="/tmp/alice2")

    def test_get_account(self, db: AccountDB):
        acc_id = db.add_account(name="alice", storage_path="/tmp/alice")
        fetched = db.get_account(acc_id)
        assert fetched is not None
        assert fetched.name == "alice"

    def test_update_account(self, db: AccountDB):
        acc_id = db.add_account(name="alice", storage_path="/tmp/alice")
        db.update_account(acc_id, status="active", user_id="u123")
        updated = db.get_account(acc_id)
        assert updated is not None
        assert updated.status == "active"
        assert updated.user_id == "u123"

    def test_list_accounts(self, db: AccountDB):
        db.add_account(name="alice", storage_path="/tmp/alice")
        db.add_account(name="bob", storage_path="/tmp/bob")
        accounts = db.list_accounts()
        assert len(accounts) == 2

    def test_delete_account(self, db: AccountDB):
        acc_id = db.add_account(name="alice", storage_path="/tmp/alice")
        db.delete_account(acc_id)
        assert db.get_account(acc_id) is None

    def test_session_binding(self, db: AccountDB):
        acc_id = db.add_account(name="alice", storage_path="/tmp/alice")
        db.set_binding("session-1", acc_id)
        binding = db.get_binding("session-1")
        assert binding is not None
        assert binding.account_id == acc_id

    def test_rebind_session(self, db: AccountDB):
        acc1 = db.add_account(name="alice", storage_path="/tmp/alice")
        acc2 = db.add_account(name="bob", storage_path="/tmp/bob")
        db.set_binding("session-1", acc1)
        db.set_binding("session-1", acc2)
        binding = db.get_binding("session-1")
        assert binding is not None
        assert binding.account_id == acc2

    def test_unbind_session(self, db: AccountDB):
        acc_id = db.add_account(name="alice", storage_path="/tmp/alice")
        db.set_binding("session-1", acc_id)
        db.delete_binding("session-1")
        assert db.get_binding("session-1") is None

    def test_record_event(self, db: AccountDB):
        acc_id = db.add_account(name="alice", storage_path="/tmp/alice")
        db.record_event("login_success", account_id=acc_id, detail="ok")
        events = db.list_events(limit=10)
        assert len(events) == 1
        assert events[0]["event_type"] == "login_success"
