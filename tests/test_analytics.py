import sqlite3

import pytest

from video_service.app import main

pytestmark = pytest.mark.unit


def _build_conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_stats (
            id TEXT PRIMARY KEY,
            completed_at TEXT NOT NULL,
            status TEXT NOT NULL,
            mode TEXT,
            brand TEXT,
            category TEXT,
            category_id TEXT,
            duration_seconds REAL,
            scan_mode TEXT,
            provider TEXT,
            model_name TEXT,
            ocr_engine TEXT,
            source_type TEXT
        )
        """
    )
    conn.commit()
    return conn


def test_get_analytics_returns_expected_shape_when_empty(tmp_path, monkeypatch):
    db_path = str(tmp_path / "analytics_empty.db")
    conn = _build_conn(db_path)
    conn.close()

    def _get_db():
        return _build_conn(db_path)

    monkeypatch.setattr(main, "get_db", _get_db)

    payload = main.get_analytics()

    assert payload["top_brands"] == []
    assert payload["categories"] == []
    assert payload["avg_duration_by_mode"] == []
    assert payload["avg_duration_by_scan"] == []
    assert payload["daily_outcomes"] == []
    assert payload["providers"] == []
    assert payload["totals"]["total"] == 0
    assert payload["totals"]["completed"] == 0
    assert payload["totals"]["failed"] == 0
    assert payload["totals"]["avg_duration"] is None


def test_get_analytics_aggregates_and_filters_unknown_brand(tmp_path, monkeypatch):
    db_path = str(tmp_path / "analytics_data.db")
    conn = _build_conn(db_path)
    conn.executemany(
        """
        INSERT INTO job_stats (
            id, completed_at, status, mode, brand, category, category_id,
            duration_seconds, scan_mode, provider, model_name, ocr_engine, source_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "node-a-1",
                "2026-02-27T10:00:00Z",
                "completed",
                "pipeline",
                "Volvo",
                "Automotive",
                "101",
                18.5,
                "Tail Only",
                "Ollama",
                "qwen3-vl:8b-instruct",
                "EasyOCR",
                "url",
            ),
            (
                "node-a-2",
                "2026-02-27T11:00:00Z",
                "completed",
                "agent",
                "Unknown",
                "Unknown",
                "",
                31.0,
                "Full Video",
                "Ollama",
                "qwen3-vl:8b-instruct",
                "EasyOCR",
                "local",
            ),
            (
                "node-a-3",
                "2026-02-27T12:00:00Z",
                "failed",
                "pipeline",
                "",
                "",
                "",
                None,
                "Tail Only",
                "Ollama",
                "qwen3-vl:8b-instruct",
                "EasyOCR",
                "url",
            ),
        ],
    )
    conn.commit()
    conn.close()

    def _get_db():
        return _build_conn(db_path)

    monkeypatch.setattr(main, "get_db", _get_db)

    payload = main.get_analytics()

    assert payload["totals"]["total"] == 3
    assert payload["totals"]["completed"] == 2
    assert payload["totals"]["failed"] == 1
    assert payload["top_brands"] == [{"brand": "Volvo", "count": 1}]
    assert payload["categories"] == [{"category": "Automotive", "count": 1}]
    assert payload["providers"] == [{"provider": "Ollama", "count": 2}]
    assert payload["avg_duration_by_mode"][0]["avg_duration"] in {18.5, 31.0}
    assert payload["daily_outcomes"][0]["day"] == "2026-02-27"
