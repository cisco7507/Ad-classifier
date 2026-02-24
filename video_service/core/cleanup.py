"""
video_service/core/cleanup.py
================================
Background TTL cleanup job.

- Deletes DB rows older than JOB_TTL_DAYS (default: 30)
- Removes orphaned artifact directories under ARTIFACTS_DIR
- Removes completed upload temp files under UPLOAD_DIR
- Runs every CLEANUP_INTERVAL_HOURS hours (default: 6)

Enable by calling  start_cleanup_thread()  from app startup.
"""

import os
import shutil
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
JOB_TTL_DAYS: int         = int(os.environ.get("JOB_TTL_DAYS", "30"))
CLEANUP_INTERVAL_HOURS: float = float(os.environ.get("CLEANUP_INTERVAL_HOURS", "6"))
ARTIFACTS_DIR: str        = os.environ.get("ARTIFACTS_DIR", "/tmp/video_service_artifacts")
UPLOAD_DIR: str           = os.environ.get("UPLOAD_DIR", "/tmp/video_service_uploads")
DB_PATH: str              = os.environ.get("DATABASE_PATH", "video_service.db")
CLEANUP_ENABLED: bool     = os.environ.get("CLEANUP_ENABLED", "true").lower() in ("1", "true", "yes")


# ── Core cleanup logic ────────────────────────────────────────────────────────

def _prune_old_jobs() -> int:
    """Delete DB rows for jobs older than JOB_TTL_DAYS. Returns # deleted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=JOB_TTL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        with conn:
            cur = conn.execute(
                "DELETE FROM jobs WHERE created_at < ? AND status IN ('completed','failed')",
                (cutoff,)
            )
            deleted = cur.rowcount
        conn.close()
        if deleted:
            logger.info("cleanup: pruned %d old job rows (cutoff=%s)", deleted, cutoff)
        return deleted
    except Exception as exc:
        logger.error("cleanup: DB prune failed: %s", exc)
        return 0


def _prune_artifact_dirs() -> int:
    """
    Walk ARTIFACTS_DIR and remove any sub-directory whose corresponding
    job no longer exists in the DB (orphaned) or whose job is older than TTL.
    Returns # dirs removed.
    """
    if not os.path.isdir(ARTIFACTS_DIR):
        return 0

    removed = 0
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        live_ids: set[str] = {
            row[0] for row in conn.execute("SELECT id FROM jobs").fetchall()
        }
        conn.close()

        for entry in os.scandir(ARTIFACTS_DIR):
            if entry.is_dir() and entry.name not in live_ids:
                try:
                    shutil.rmtree(entry.path)
                    logger.info("cleanup: removed orphaned artifact dir %s", entry.path)
                    removed += 1
                except Exception as exc:
                    logger.warning("cleanup: could not remove %s: %s", entry.path, exc)
    except Exception as exc:
        logger.error("cleanup: artifact prune failed: %s", exc)

    return removed


def _prune_upload_temp_files() -> int:
    """
    Remove temp upload files older than JOB_TTL_DAYS from UPLOAD_DIR.
    Returns # files removed.
    """
    if not os.path.isdir(UPLOAD_DIR):
        return 0

    cutoff_ts = time.time() - JOB_TTL_DAYS * 86400
    removed = 0
    try:
        for entry in os.scandir(UPLOAD_DIR):
            if entry.is_file() and entry.stat().st_mtime < cutoff_ts:
                try:
                    os.remove(entry.path)
                    removed += 1
                except Exception as exc:
                    logger.warning("cleanup: could not remove upload %s: %s", entry.path, exc)
    except Exception as exc:
        logger.error("cleanup: upload prune failed: %s", exc)

    return removed


def run_cleanup_once() -> dict:
    """Run all cleanup tasks once. Returns a summary dict."""
    jobs_deleted    = _prune_old_jobs()
    arts_removed    = _prune_artifact_dirs()
    uploads_removed = _prune_upload_temp_files()
    summary = {"jobs_deleted": jobs_deleted, "artifact_dirs_removed": arts_removed, "upload_files_removed": uploads_removed}
    logger.info("cleanup: run complete %s", summary)
    return summary


def _cleanup_loop() -> None:
    interval_s = CLEANUP_INTERVAL_HOURS * 3600
    logger.info("cleanup: thread started (interval=%.1fh, ttl=%dd)", CLEANUP_INTERVAL_HOURS, JOB_TTL_DAYS)
    while True:
        try:
            run_cleanup_once()
        except Exception as exc:
            logger.error("cleanup: unhandled error in loop: %s", exc)
        time.sleep(interval_s)


def start_cleanup_thread() -> threading.Thread | None:
    """Start the background cleanup thread if CLEANUP_ENABLED=true."""
    if not CLEANUP_ENABLED:
        logger.info("cleanup: disabled (CLEANUP_ENABLED=false)")
        return None
    t = threading.Thread(target=_cleanup_loop, daemon=True, name="cleanup-thread")
    t.start()
    return t
