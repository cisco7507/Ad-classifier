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
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from video_service.core.logging_setup import (
    configure_logging,
    reset_job_context,
    reset_stage_context,
    set_job_context,
    set_stage_context,
)

configure_logging()

from video_service.db.database import get_db, init_db
from video_service.core import run_pipeline_job, run_agent_job
from video_service.core.device import get_diagnostics, DEVICE

logger = logging.getLogger(__name__)


def _short(text: str | None, max_len: int = 220) -> str:
    if not text:
        return ""
    compact = " ".join(str(text).split())
    return compact[:max_len]


def _append_job_event(job_id: str, message: str) -> None:
    try:
        with get_db() as conn:
            row = conn.execute("SELECT events FROM jobs WHERE id = ?", (job_id,)).fetchone()
            events = []
            if row and row["events"]:
                try:
                    events = json.loads(row["events"])
                except Exception:
                    events = []

            events.append(message)
            # Keep event payload bounded.
            events = events[-400:]
            conn.execute(
                "UPDATE jobs SET events = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(events), job_id),
            )
    except Exception as exc:
        logger.warning("event_append_failed: %s", exc)


def _set_stage(
    job_id: str,
    stage: str,
    detail: str,
    *,
    status: str | None = None,
    error: str | None = None,
) -> None:
    stage_name = stage or "-"
    detail_msg = _short(detail)
    set_stage_context(stage_name, detail_msg)

    sql = "UPDATE jobs SET stage = ?, stage_detail = ?, updated_at = CURRENT_TIMESTAMP"
    params: list[str] = [stage_name, detail_msg]
    if status is not None:
        sql += ", status = ?"
        params.append(status)
    if error is not None:
        sql += ", error = ?"
        params.append(error[:4096])
    sql += " WHERE id = ?"
    params.append(job_id)

    with get_db() as conn:
        conn.execute(sql, tuple(params))

    logger.info("%s", detail_msg)
    _append_job_event(
        job_id,
        f"{datetime.now(timezone.utc).isoformat()} {stage_name}: {detail_msg}",
    )


def _stage_callback(job_id: str):
    def callback(stage: str, detail: str) -> None:
        _set_stage(job_id, stage, detail)
    return callback


def claim_and_process_job() -> bool:
    conn = get_db()
    job_token = None
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
            "UPDATE jobs SET status = 'processing', stage = 'claim', stage_detail = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            ("worker claimed job", job_id),
        )
        conn.commit()

        job_token = set_job_context(job_id)
        set_stage_context("claim", "worker claimed job")
        logger.info("worker claimed job (device=%s)", DEVICE)
        _append_job_event(
            job_id,
            f"{datetime.now(timezone.utc).isoformat()} claim: worker claimed job",
        )

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
            logger.exception("job_error")
            error_msg = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"

        # Persist result
        with get_db() as update_conn:
            if error_msg:
                _set_stage(
                    job_id,
                    "failed",
                    f"job failed: {_short(error_msg, 180)}",
                    status="failed",
                    error=error_msg,
                )
                logger.error("job_failed: error=%.200s", error_msg)
            else:
                _set_stage(job_id, "persist", "persisting result payload")
                update_conn.execute(
                    "UPDATE jobs SET status = 'completed', stage = 'completed', stage_detail = ?, progress = 100, result_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    ("result persisted", result_json, job_id),
                )
                _append_job_event(
                    job_id,
                    f"{datetime.now(timezone.utc).isoformat()} completed: result persisted",
                )
                set_stage_context("completed", "result persisted")
                logger.info("job_completed")

        return True

    except Exception as exc:
        conn.rollback()
        logger.error("worker_lock_error: %s", exc)
        return False
    finally:
        reset_stage_context()
        reset_job_context(job_token)


def _run_pipeline(job_id: str, url: str, settings: dict) -> str | None:
    stage_cb = _stage_callback(job_id)
    stage_cb("ingest", "validating input parameters")
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
        stage_callback=stage_cb,
    )
    final_df = None
    for content in generator:
        if len(content) == 5:
            final_df = content[4]

    if final_df is not None and not final_df.empty:
        result = json.dumps(final_df.to_dict(orient="records"))
        logger.info("pipeline_done: rows=%d", len(final_df))
        return result

    logger.warning("pipeline_empty: no result rows")
    return None


def _run_agent(job_id: str, url: str, settings: dict) -> tuple[str | None, list[str]]:
    events: list[str] = []
    stage_cb = _stage_callback(job_id)
    stage_cb("ingest", "validating input parameters")
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
        stage_callback=stage_cb,
    )
    final_df = None
    for content in generator:
        if len(content) == 4:
            log_str, gallery, df, nebula = content
            events.append(log_str)
            final_df = df
            agent_log = log_str or ""
            if len(agent_log) > 12000:
                agent_log = f"{agent_log[:12000]}\n...[truncated]"
            _append_job_event(
                job_id,
                f"{datetime.now(timezone.utc).isoformat()} agent:\n{agent_log}",
            )
            logger.debug("agent_event: events=%d", len(events))

    result_json = None
    if final_df is not None and not final_df.empty:
        result_json = json.dumps(final_df.to_dict(orient="records"))
        logger.info("agent_done: rows=%d events=%d", len(final_df), len(events))
    else:
        logger.warning("agent_empty: no result rows")

    return result_json, events


def run_worker() -> None:
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
