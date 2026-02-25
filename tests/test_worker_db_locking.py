import json
import sqlite3

import pytest

from video_service.workers import worker

pytestmark = pytest.mark.unit


class _Ctx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        return False


def test_execute_job_update_with_retry_retries_on_locked(monkeypatch):
    calls = {"n": 0}

    class _Conn:
        def execute(self, _sql, _params):
            calls["n"] += 1
            if calls["n"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return None

    monkeypatch.setattr(worker, "get_db", lambda: _Ctx(_Conn()))
    monkeypatch.setattr(worker.time, "sleep", lambda _secs: None)

    worker._execute_job_update_with_retry("UPDATE jobs SET stage = ? WHERE id = ?", ("ocr", "job-1"))
    assert calls["n"] == 2


def test_execute_job_update_with_retry_raises_non_lock_error(monkeypatch):
    class _Conn:
        def execute(self, _sql, _params):
            raise sqlite3.OperationalError("no such table: jobs")

    monkeypatch.setattr(worker, "get_db", lambda: _Ctx(_Conn()))
    with pytest.raises(sqlite3.OperationalError):
        worker._execute_job_update_with_retry("UPDATE jobs SET stage = ? WHERE id = ?", ("ocr", "job-1"))


def test_append_job_event_retries_on_locked(monkeypatch):
    state = {"attempt": 0, "updated_payload": None}

    class _Conn:
        def execute(self, sql, params=()):
            if sql.startswith("BEGIN IMMEDIATE"):
                return None
            if sql.startswith("SELECT events"):
                return type("Result", (), {"fetchone": staticmethod(lambda: {"events": "[]"})})()
            if sql.startswith("UPDATE jobs SET events"):
                state["attempt"] += 1
                if state["attempt"] == 1:
                    raise sqlite3.OperationalError("database is locked")
                state["updated_payload"] = params[0]
                return None
            return None

    monkeypatch.setattr(worker, "get_db", lambda: _Ctx(_Conn()))
    monkeypatch.setattr(worker.time, "sleep", lambda _secs: None)

    worker._append_job_event("job-1", "evt")
    assert state["attempt"] == 2
    assert json.loads(state["updated_payload"]) == ["evt"]
