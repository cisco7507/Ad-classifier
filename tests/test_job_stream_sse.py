import asyncio
import sqlite3

import pytest

from video_service.app import main

pytestmark = pytest.mark.unit


class _Req:
    query_params = {}

    def __init__(self) -> None:
        self._checks = 0

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > 5


async def _collect_chunks(response, max_chunks: int = 4) -> list[str]:
    collected: list[str] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            collected.append(chunk.decode("utf-8", errors="ignore"))
        else:
            collected.append(str(chunk))
        if len(collected) >= max_chunks:
            break
    return collected


def test_job_stream_sse_returns_error_for_missing_job(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                status TEXT,
                stage TEXT,
                stage_detail TEXT,
                progress REAL,
                error TEXT,
                updated_at TEXT,
                events TEXT
            )
            """
        )

    monkeypatch.setattr(main, "get_db", lambda: conn)
    response = asyncio.run(main.stream_job_events(_Req(), "node-a-missing"))
    chunks = asyncio.run(_collect_chunks(response, max_chunks=1))
    rendered = "".join(chunks)
    assert "'event': 'error'" in rendered
    assert "Job not found" in rendered


def test_job_stream_sse_emits_update_then_complete_for_terminal_job(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                status TEXT,
                stage TEXT,
                stage_detail TEXT,
                progress REAL,
                error TEXT,
                updated_at TEXT,
                events TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO jobs (id, status, stage, stage_detail, progress, error, updated_at, events)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "node-a-job-1",
                "completed",
                "completed",
                "done",
                100.0,
                None,
                "2026-02-27 18:00:00",
                '["2026-02-27T18:00:00Z completed: done"]',
            ),
        )

    monkeypatch.setattr(main, "get_db", lambda: conn)
    response = asyncio.run(main.stream_job_events(_Req(), "node-a-job-1"))
    chunks = asyncio.run(_collect_chunks(response, max_chunks=3))
    rendered = "".join(chunks)
    assert "'event': 'update'" in rendered
    assert "'event': 'complete'" in rendered
    assert '"status": "completed"' in rendered
