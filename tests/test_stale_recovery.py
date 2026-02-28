import json
import sqlite3
import logging
from datetime import datetime, timedelta, timezone

import pytest

from video_service.app import main
from video_service.core import stale_recovery

pytestmark = pytest.mark.unit


def _make_conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            stage TEXT,
            stage_detail TEXT,
            updated_at TEXT,
            events TEXT DEFAULT '[]'
        )
        """
    )
    conn.commit()
    return conn


def test_startup_recovery_resets_processing_and_appends_event(tmp_path, monkeypatch):
    db_path = str(tmp_path / "startup_recovery.db")
    conn = _make_conn(db_path)
    conn.execute(
        "INSERT INTO jobs (id, status, stage, stage_detail, updated_at, events) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "node-a-1",
            "processing",
            "ocr",
            "running",
            "2026-02-27 10:00:00",
            "[]",
        ),
    )
    conn.execute(
        "INSERT INTO jobs (id, status, stage, stage_detail, updated_at, events) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "node-a-2",
            "queued",
            "queued",
            "waiting",
            "2026-02-27 10:00:00",
            "[]",
        ),
    )
    conn.commit()
    conn.close()

    def _get_db():
        return _make_conn(db_path)

    monkeypatch.setattr(main, "get_db", _get_db)

    recovered = main._recover_stale_jobs_on_startup()

    assert recovered == 1

    check = _make_conn(db_path)
    row = check.execute("SELECT * FROM jobs WHERE id = ?", ("node-a-1",)).fetchone()
    assert row["status"] == "queued"
    assert row["stage"] == "queued"
    assert row["stage_detail"] == "recovered after restart"
    events = json.loads(row["events"])
    assert any("recovered after process restart" in event for event in events)
    check.close()


def test_watchdog_recovery_only_resets_stale_processing_jobs(tmp_path, monkeypatch):
    db_path = str(tmp_path / "watchdog_recovery.db")
    conn = _make_conn(db_path)
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    fresh_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    conn.executemany(
        "INSERT INTO jobs (id, status, stage, stage_detail, updated_at, events) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("stale-job", "processing", "llm", "running", stale_ts, "[]"),
            ("fresh-job", "processing", "llm", "running", fresh_ts, "[]"),
            ("queued-job", "queued", "queued", "waiting", stale_ts, "[]"),
        ],
    )
    conn.commit()
    conn.close()

    def _get_db():
        return _make_conn(db_path)

    monkeypatch.setattr(stale_recovery, "get_db", _get_db)
    monkeypatch.setattr(stale_recovery, "STALE_TIMEOUT_SECONDS", 600)

    recovered = stale_recovery._recover_stale_jobs()

    assert recovered == 1

    check = _make_conn(db_path)
    stale_row = check.execute("SELECT * FROM jobs WHERE id = ?", ("stale-job",)).fetchone()
    fresh_row = check.execute("SELECT * FROM jobs WHERE id = ?", ("fresh-job",)).fetchone()
    assert stale_row["status"] == "re-queued"
    assert stale_row["stage"] == "re-queued"
    assert stale_row["stage_detail"] == "recovered by watchdog (stale timeout)"
    events = json.loads(stale_row["events"])
    assert any("recovered by watchdog (stale timeout)" in event for event in events)
    assert fresh_row["status"] == "processing"
    check.close()


def test_watchdog_recovery_logs_recovered_job_ids(tmp_path, monkeypatch, caplog):
    db_path = str(tmp_path / "watchdog_recovery_log_ids.db")
    conn = _make_conn(db_path)
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO jobs (id, status, stage, stage_detail, updated_at, events) VALUES (?, ?, ?, ?, ?, ?)",
        ("stale-log-job", "processing", "vision", "running", stale_ts, "[]"),
    )
    conn.commit()
    conn.close()

    def _get_db():
        return _make_conn(db_path)

    monkeypatch.setattr(stale_recovery, "get_db", _get_db)
    monkeypatch.setattr(stale_recovery, "STALE_TIMEOUT_SECONDS", 600)
    caplog.set_level(logging.INFO, logger=stale_recovery.__name__)

    recovered = stale_recovery._recover_stale_jobs()
    assert recovered == 1
    assert "stale-log-job" in caplog.text
