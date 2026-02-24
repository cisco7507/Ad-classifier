import importlib
import io
import logging
import os
import sqlite3
from pathlib import Path

import pytest

import video_service.app.main as main
import video_service.core.logging_setup as logging_setup
import video_service.db.database as database

pytestmark = pytest.mark.unit


def test_init_db_migrates_legacy_jobs_table_with_stage_columns(tmp_path: Path):
    original_database_path = os.environ.get("DATABASE_PATH")
    db_path = tmp_path / "legacy_jobs.db"

    os.environ["DATABASE_PATH"] = str(db_path)
    try:
        importlib.reload(database)

        conn = sqlite3.connect(database.DB_PATH)
        with conn:
            conn.execute(
                """
                CREATE TABLE jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    progress REAL DEFAULT 0,
                    error TEXT,
                    settings TEXT,
                    mode TEXT,
                    url TEXT,
                    result_json TEXT,
                    artifacts_json TEXT,
                    events TEXT DEFAULT '[]'
                )
                """
            )
            conn.execute(
                "INSERT INTO jobs (id, status, settings, mode, url, events) VALUES (?, ?, ?, ?, ?, ?)",
                ("job-legacy-1", "processing", "{}", "pipeline", "https://example.test/a.mp4", "[]"),
            )

        database.init_db()

        conn = sqlite3.connect(database.DB_PATH)
        conn.row_factory = sqlite3.Row
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        assert "stage" in cols
        assert "stage_detail" in cols

        migrated_row = conn.execute(
            "SELECT stage, stage_detail FROM jobs WHERE id = ?",
            ("job-legacy-1",),
        ).fetchone()
        assert migrated_row["stage"] == "processing"
        assert migrated_row["stage_detail"] == ""
    finally:
        if original_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = original_database_path
        importlib.reload(database)


def test_get_jobs_from_db_includes_stage_and_stage_detail(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with conn:
        conn.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                stage TEXT,
                stage_detail TEXT,
                created_at TEXT,
                updated_at TEXT,
                progress REAL,
                error TEXT,
                settings TEXT,
                mode TEXT,
                url TEXT,
                result_json TEXT,
                artifacts_json TEXT,
                events TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO jobs (
                id, status, stage, stage_detail, created_at, updated_at, progress, error, settings, mode, url, result_json, artifacts_json, events
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "node-a-123",
                "processing",
                "ocr",
                "ocr engine=easyocr",
                "2026-02-24 10:00:00",
                "2026-02-24 10:01:00",
                33.3,
                None,
                '{"categories":"","provider":"Ollama","model_name":"qwen3-vl:8b-instruct","ocr_engine":"EasyOCR","ocr_mode":"🚀 Fast","scan_mode":"Tail Only","override":false,"enable_search":true,"enable_vision":true,"context_size":8192,"workers":1}',
                "pipeline",
                "https://example.test/video.mp4",
                None,
                None,
                "[]",
            ),
        )

    monkeypatch.setattr(main, "get_db", lambda: conn)
    jobs = main._get_jobs_from_db()

    assert len(jobs) == 1
    assert jobs[0].stage == "ocr"
    assert jobs[0].stage_detail == "ocr engine=easyocr"


def test_logging_context_filter_injects_job_and_stage():
    importlib.reload(logging_setup)

    logger = logging.getLogger("tests.observability")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("job_id=%(job_id)s stage=%(stage)s %(message)s"))
    handler.addFilter(logging_setup.ContextEnricherFilter())
    logger.addHandler(handler)

    job_token = logging_setup.set_job_context("node-a-job-1")
    stage_tokens = logging_setup.set_stage_context("llm", "calling provider=openai")
    try:
        logger.info("classification call")
    finally:
        logging_setup.reset_stage_context(stage_tokens)
        logging_setup.reset_job_context(job_token)
        logger.removeHandler(handler)

    out = stream.getvalue()
    assert "job_id=node-a-job-1" in out
    assert "stage=llm" in out
    assert "classification call" in out
