"""
video_service/workers/worker.py
================================
Background worker — claims queued jobs from SQLite and processes them.

Structured logging: all log lines include job_id for correlation.
Never uses print() in hot paths; structured logger used throughout.
"""

import time
import os
import sys
import json
import logging
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from video_service.db.database import get_db, init_db
from video_service.core import run_pipeline_job, run_agent_job
from video_service.core.device import get_diagnostics, DEVICE

logger = logging.getLogger(__name__)


def claim_and_process_job() -> bool:
    conn = get_db()
    try:
        cur = conn.cursor()
        conn.execute("BEGIN EXCLUSIVE")

        cur.execute("SELECT * FROM jobs WHERE status = 'queued' LIMIT 1")
        row = cur.fetchone()

        if not row:
            conn.rollback()
            return False

        job_id = row["id"]
        cur.execute(
            "UPDATE jobs SET status = 'processing', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (job_id,),
        )
        conn.commit()

        logger.info("job_claimed: job_id=%s device=%s", job_id, DEVICE)

        url      = row["url"]
        mode     = row["mode"]
        settings = json.loads(row["settings"]) if row["settings"] else {}

        events: list[str] = []
        result_json: str | None = None
        error_msg:   str | None = None

        try:
            if mode == "pipeline":
                result_json = _run_pipeline(job_id, url, settings)
            elif mode == "agent":
                result_json, events = _run_agent(job_id, url, settings)
            else:
                raise ValueError(f"Unknown mode: {mode}")

        except Exception as exc:
            logger.exception("job_error: job_id=%s", job_id)
            error_msg = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"

        # Persist result
        with get_db() as update_conn:
            if error_msg:
                update_conn.execute(
                    "UPDATE jobs SET status = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (error_msg[:4096], job_id),
                )
                logger.error("job_failed: job_id=%s error=%.200s", job_id, error_msg)
            else:
                update_conn.execute(
                    "UPDATE jobs SET status = 'completed', progress = 100, result_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (result_json, job_id),
                )
                logger.info("job_completed: job_id=%s", job_id)

        return True

    except Exception as exc:
        conn.rollback()
        logger.error("worker_lock_error: %s", exc)
        return False


def _run_pipeline(job_id: str, url: str, settings: dict) -> str | None:
    generator = run_pipeline_job(
        job_id=job_id,
        src="Web URLs",
        urls=url,
        fldr="",
        cats=settings.get("categories", ""),
        p=settings.get("provider", "Ollama"),
        m=settings.get("model_name", "qwen3-vl:8b-instruct"),
        oe=settings.get("ocr_engine", "EasyOCR"),
        om=settings.get("ocr_mode", "🚀 Fast"),
        override=settings.get("override", False),
        sm=settings.get("scan_mode", "Tail Only"),
        enable_search=settings.get("enable_search", False),
        enable_vision=settings.get("enable_vision", False),
        ctx=settings.get("context_size", 8192),
        workers=1,
    )
    final_df = None
    for content in generator:
        if len(content) == 5:
            final_df = content[4]

    if final_df is not None and not final_df.empty:
        result = json.dumps(final_df.to_dict(orient="records"))
        logger.info("pipeline_done: job_id=%s rows=%d", job_id, len(final_df))
        return result

    logger.warning("pipeline_empty: job_id=%s — no result rows", job_id)
    return None


def _run_agent(job_id: str, url: str, settings: dict) -> tuple[str | None, list[str]]:
    events: list[str] = []
    generator = run_agent_job(
        job_id=job_id,
        src="Web URLs",
        urls=url,
        fldr="",
        cats=settings.get("categories", ""),
        p=settings.get("provider", "Ollama"),
        m=settings.get("model_name", "qwen3-vl:8b-instruct"),
        oe=settings.get("ocr_engine", "EasyOCR"),
        om=settings.get("ocr_mode", "🚀 Fast"),
        override=settings.get("override", False),
        sm=settings.get("scan_mode", "Tail Only"),
        enable_search=settings.get("enable_search", False),
        enable_vision=settings.get("enable_vision", False),
        ctx=settings.get("context_size", 8192),
    )
    final_df = None
    for content in generator:
        if len(content) == 4:
            log_str, gallery, df, nebula = content
            events.append(log_str)
            final_df = df
            with get_db() as uconn:
                uconn.execute(
                    "UPDATE jobs SET events = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(events), job_id),
                )
            logger.debug("agent_event: job_id=%s events=%d", job_id, len(events))

    result_json = None
    if final_df is not None and not final_df.empty:
        result_json = json.dumps(final_df.to_dict(orient="records"))
        logger.info("agent_done: job_id=%s rows=%d events=%d", job_id, len(final_df), len(events))
    else:
        logger.warning("agent_empty: job_id=%s — no result rows", job_id)

    return result_json, events


def run_worker() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger.info("worker_start: diagnostics=%s", json.dumps(get_diagnostics()))
    init_db()
    while True:
        try:
            processed = claim_and_process_job()
        except Exception as exc:
            logger.error("worker_loop_error: %s", exc)
            processed = False
        if not processed:
            time.sleep(1)


if __name__ == "__main__":
    run_worker()
