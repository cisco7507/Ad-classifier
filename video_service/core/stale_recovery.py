"""Background watchdog for recovering stale processing jobs."""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import closing
from datetime import datetime, timezone

from video_service.db.database import get_db

logger = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("stale_recovery: invalid int for %s=%r; using %d", name, raw, default)
        return default


STALE_TIMEOUT_SECONDS = _int_env("STALE_JOB_TIMEOUT_SECONDS", 600)
CHECK_INTERVAL_SECONDS = max(1, _int_env("STALE_JOB_CHECK_INTERVAL_SECONDS", 60))

_shutdown = threading.Event()
_thread_lock = threading.Lock()
_watchdog_thread: threading.Thread | None = None


def _append_recovery_event(conn, job_id: str, message: str) -> None:
    row = conn.execute("SELECT events FROM jobs WHERE id = ?", (job_id,)).fetchone()
    events: list[str] = []
    if row and row["events"]:
        try:
            parsed = json.loads(row["events"])
            if isinstance(parsed, list):
                events = [str(item) for item in parsed]
        except Exception:
            events = []

    events.append(f"{datetime.now(timezone.utc).isoformat()} recovery: {message}")
    events = events[-400:]
    conn.execute(
        "UPDATE jobs SET events = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(events), job_id),
    )


def _recover_stale_jobs() -> int:
    """Reset processing jobs that have exceeded the stale timeout."""
    if STALE_TIMEOUT_SECONDS <= 0:
        return 0

    with closing(get_db()) as conn:
        candidates = conn.execute(
            """
            SELECT id
            FROM jobs
            WHERE status = 'processing'
              AND updated_at < datetime('now', ?)
            """,
            (f"-{STALE_TIMEOUT_SECONDS} seconds",),
        ).fetchall()
        job_ids = [row["id"] for row in candidates]
        if not job_ids:
            return 0

        placeholders = ",".join("?" for _ in job_ids)
        with conn:
            conn.execute(
                f"""
                UPDATE jobs
                SET status = 'queued',
                    stage = 'queued',
                    stage_detail = 'recovered by watchdog (stale timeout)',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                  AND status = 'processing'
                  AND updated_at < datetime('now', ?)
                """,
                (*tuple(job_ids), f"-{STALE_TIMEOUT_SECONDS} seconds"),
            )
            recovered_rows = conn.execute(
                f"""
                SELECT id
                FROM jobs
                WHERE id IN ({placeholders})
                  AND status = 'queued'
                  AND stage_detail = 'recovered by watchdog (stale timeout)'
                """,
                tuple(job_ids),
            ).fetchall()
            recovered_ids = [row["id"] for row in recovered_rows]
            for job_id in recovered_ids:
                _append_recovery_event(
                    conn,
                    job_id,
                    "recovered by watchdog (stale timeout)",
                )

    logger.info(
        "stale_recovery: reset %d stale processing jobs to queued",
        len(recovered_ids),
    )
    return len(recovered_ids)


def _watchdog_loop() -> None:
    logger.info(
        "stale_recovery: watchdog started (timeout=%ds, interval=%ds)",
        STALE_TIMEOUT_SECONDS,
        CHECK_INTERVAL_SECONDS,
    )
    while not _shutdown.is_set():
        try:
            _recover_stale_jobs()
        except Exception as exc:
            logger.error("stale_recovery: check failed: %s", exc)
        _shutdown.wait(timeout=CHECK_INTERVAL_SECONDS)


def start_stale_recovery_thread() -> threading.Thread | None:
    """Start stale processing watchdog; returns None when disabled."""
    global _watchdog_thread
    if STALE_TIMEOUT_SECONDS <= 0:
        logger.info("stale_recovery: disabled (STALE_JOB_TIMEOUT_SECONDS=0)")
        return None

    with _thread_lock:
        if _watchdog_thread and _watchdog_thread.is_alive():
            return _watchdog_thread
        _shutdown.clear()
        _watchdog_thread = threading.Thread(
            target=_watchdog_loop,
            daemon=True,
            name="stale-recovery",
        )
        _watchdog_thread.start()
        return _watchdog_thread


def stop_stale_recovery() -> None:
    """Signal stale recovery watchdog to stop."""
    _shutdown.set()
