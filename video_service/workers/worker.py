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
import re
import logging
import traceback
import multiprocessing
from datetime import datetime, timezone
from pathlib import Path

import cv2

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
from video_service.core.concurrency import (
    get_concurrency_diagnostics,
    get_pipeline_threads_per_job,
    get_worker_processes_config,
)
from video_service.core.device import get_diagnostics, DEVICE

logger = logging.getLogger(__name__)
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "/tmp/video_service_artifacts"))
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _short(text: str | None, max_len: int = 220) -> str:
    if not text:
        return ""
    compact = " ".join(str(text).split())
    return compact[:max_len]


def _sanitize_job_id(job_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", job_id or "")


def _resolve_enable_web_search(settings: dict) -> bool:
    if "enable_web_search" in settings:
        return bool(settings.get("enable_web_search"))
    if "enable_agentic_search" in settings:
        return bool(settings.get("enable_agentic_search"))
    return bool(settings.get("enable_search", False))


def _build_default_artifacts(job_id: str) -> dict:
    return {
        "latest_frames": [],
        "ocr_text": {"text": "", "lines": [], "url": None},
        "vision_board": {"image_url": None, "plot_url": None, "top_matches": [], "metadata": {}},
        "extras": {"events_url": f"/jobs/{job_id}/events"},
    }


def _extract_timestamp_seconds(label: str) -> float | None:
    if not label:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)s", str(label))
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _write_text_artifact(job_id: str, relative_name: str, text: str) -> str | None:
    if not text:
        return None
    safe_job = _sanitize_job_id(job_id)
    rel_path = Path(safe_job) / relative_name
    abs_path = ARTIFACTS_DIR / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(text, encoding="utf-8")
    return f"/artifacts/{rel_path.as_posix()}"


def _save_gallery_frames(job_id: str, gallery: list) -> list[dict]:
    frames: list[dict] = []
    safe_job = _sanitize_job_id(job_id)
    rel_dir = Path(safe_job) / "latest_frames"
    abs_dir = ARTIFACTS_DIR / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    for idx, item in enumerate(gallery or []):
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            continue
        image_obj, label = item[0], str(item[1])
        if image_obj is None:
            continue
        filename = f"frame_{idx+1:03d}.jpg"
        rel_path = rel_dir / filename
        abs_path = ARTIFACTS_DIR / rel_path
        try:
            cv2.imwrite(str(abs_path), image_obj)
        except Exception:
            continue
        frames.append(
            {
                "timestamp": _extract_timestamp_seconds(label),
                "label": label,
                "url": f"/artifacts/{rel_path.as_posix()}",
            }
        )
    return frames


def _vision_board_from_scores(scores: dict) -> dict:
    top_matches = []
    for label, score in (scores or {}).items():
        top_matches.append({"label": str(label), "score": float(score)})
    return {
        "image_url": None,
        "plot_url": None,
        "top_matches": top_matches,
        "metadata": {"source": "pipeline_scores", "count": len(top_matches)},
    }


def _vision_board_from_nebula(job_id: str, nebula) -> dict:
    board = {
        "image_url": None,
        "plot_url": None,
        "top_matches": [],
        "metadata": {"source": "agent_nebula", "count": 0},
    }
    if nebula is None or not hasattr(nebula, "to_plotly_json"):
        return board
    try:
        payload = nebula.to_plotly_json()
        raw = json.dumps(payload)
        url = _write_text_artifact(job_id, "vision_board/plotly.json", raw)
        board["plot_url"] = url
        board["metadata"]["trace_count"] = len(payload.get("data", []))
    except Exception as exc:
        logger.debug("vision_board_export_failed: %s", exc)
    return board


def _extract_summary_fields(result_json: str | None) -> tuple[str, str, str]:
    if not result_json:
        return "", "", ""
    try:
        payload = json.loads(result_json)
    except Exception:
        return "", "", ""
    if not isinstance(payload, list) or not payload:
        return "", "", ""
    row = payload[0] if isinstance(payload[0], dict) else {}
    brand = str(row.get("Brand") or row.get("brand") or "")
    category = str(row.get("Category") or row.get("category") or "")
    category_id = str(row.get("Category ID") or row.get("category_id") or "")
    return brand, category, category_id


def _extract_agent_ocr_text(events: list[str]) -> str:
    for evt in events:
        if not evt or "[Scene" not in evt:
            continue
        if "Observation:" not in evt:
            continue
        idx = evt.find("Observation:")
        if idx >= 0:
            return evt[idx + len("Observation:") :].strip()
    return ""


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
        artifacts_payload: dict = _build_default_artifacts(job_id)
        error_msg: str | None = None

        try:
            if mode == "pipeline":
                result_json, artifacts_payload = _run_pipeline(job_id, url, settings)
            elif mode == "agent":
                result_json, events, artifacts_payload = _run_agent(job_id, url, settings)
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
                brand, category, category_id = _extract_summary_fields(result_json)
                update_conn.execute(
                    "UPDATE jobs SET status = 'completed', stage = 'completed', stage_detail = ?, progress = 100, result_json = ?, artifacts_json = ?, brand = ?, category = ?, category_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (
                        "result persisted",
                        result_json,
                        json.dumps(artifacts_payload),
                        brand,
                        category,
                        category_id,
                        job_id,
                    ),
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


def _run_pipeline(job_id: str, url: str, settings: dict) -> tuple[str | None, dict]:
    stage_cb = _stage_callback(job_id)
    stage_cb("ingest", "validating input parameters")
    enable_web_search = _resolve_enable_web_search(settings)
    pipeline_threads = get_pipeline_threads_per_job()
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
        enable_search=enable_web_search,
        enable_vision=settings.get("enable_vision", False),
        ctx=settings.get("context_size", 8192),
        workers=pipeline_threads,
        stage_callback=stage_cb,
    )
    final_df = None
    latest_scores: dict = {}
    latest_ocr_text = ""
    latest_gallery = []
    for content in generator:
        if len(content) == 5:
            latest_scores = content[0] if isinstance(content[0], dict) else {}
            latest_ocr_text = content[1] if isinstance(content[1], str) else ""
            latest_gallery = content[3] if isinstance(content[3], list) else []
            final_df = content[4]

    artifacts_payload = _build_default_artifacts(job_id)
    artifacts_payload["latest_frames"] = _save_gallery_frames(job_id, latest_gallery)
    artifacts_payload["ocr_text"]["text"] = latest_ocr_text
    artifacts_payload["ocr_text"]["lines"] = [
        line for line in (latest_ocr_text or "").splitlines() if line.strip()
    ]
    artifacts_payload["ocr_text"]["url"] = _write_text_artifact(
        job_id, "ocr/ocr_output.txt", latest_ocr_text
    )
    artifacts_payload["vision_board"] = _vision_board_from_scores(latest_scores)

    if final_df is not None and not final_df.empty:
        result = json.dumps(final_df.to_dict(orient="records"))
        logger.info("pipeline_done: rows=%d", len(final_df))
        return result, artifacts_payload

    logger.warning("pipeline_empty: no result rows")
    return None, artifacts_payload


def _run_agent(job_id: str, url: str, settings: dict) -> tuple[str | None, list[str], dict]:
    events: list[str] = []
    stage_cb = _stage_callback(job_id)
    stage_cb("ingest", "validating input parameters")
    enable_web_search = _resolve_enable_web_search(settings)
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
        enable_search=enable_web_search,
        enable_vision=settings.get("enable_vision", False),
        ctx=settings.get("context_size", 8192),
        stage_callback=stage_cb,
    )
    final_df = None
    latest_gallery = []
    latest_nebula = None
    for content in generator:
        if len(content) == 4:
            log_str, gallery, df, nebula = content
            events.append(log_str)
            final_df = df
            latest_gallery = gallery if isinstance(gallery, list) else latest_gallery
            latest_nebula = nebula
            agent_log = log_str or ""
            if len(agent_log) > 12000:
                agent_log = f"{agent_log[:12000]}\n...[truncated]"
            _append_job_event(
                job_id,
                f"{datetime.now(timezone.utc).isoformat()} agent:\n{agent_log}",
            )
            logger.debug("agent_event: events=%d", len(events))

    artifacts_payload = _build_default_artifacts(job_id)
    artifacts_payload["latest_frames"] = _save_gallery_frames(job_id, latest_gallery)
    ocr_text = _extract_agent_ocr_text(events)
    artifacts_payload["ocr_text"]["text"] = ocr_text
    artifacts_payload["ocr_text"]["lines"] = [line for line in ocr_text.split(" | ") if line.strip()]
    artifacts_payload["ocr_text"]["url"] = _write_text_artifact(
        job_id, "ocr/ocr_output.txt", ocr_text
    )
    artifacts_payload["vision_board"] = _vision_board_from_nebula(job_id, latest_nebula)

    result_json = None
    if final_df is not None and not final_df.empty:
        result_json = json.dumps(final_df.to_dict(orient="records"))
        logger.info("agent_done: rows=%d events=%d", len(final_df), len(events))
    else:
        logger.warning("agent_empty: no result rows")

    return result_json, events, artifacts_payload


def run_worker() -> None:
    process_count = _get_worker_process_count()
    if process_count > 1:
        _run_worker_supervisor(process_count)
        return
    _run_single_worker()


def _run_single_worker() -> None:
    logger.info(
        "worker_start: diagnostics=%s concurrency=%s",
        json.dumps(get_diagnostics()),
        json.dumps(get_concurrency_diagnostics()),
    )
    init_db()
    while True:
        try:
            processed = claim_and_process_job()
        except Exception as exc:
            logger.error("worker_loop_error: %s", exc)
            processed = False
        if not processed:
            time.sleep(1)


def _get_worker_process_count() -> int:
    return get_worker_processes_config()


def _worker_child_main(index: int) -> None:
    logger.info("worker_child_start: index=%d", index)
    _run_single_worker()


def _spawn_worker_child(index: int) -> multiprocessing.Process:
    return multiprocessing.Process(
        target=_worker_child_main,
        kwargs={"index": index},
        name=f"worker-{index}",
        daemon=False,
    )


def _run_worker_supervisor(process_count: int) -> None:
    logger.info("worker_supervisor_start: processes=%d", process_count)
    children: list[multiprocessing.Process] = []
    for index in range(1, process_count + 1):
        proc = _spawn_worker_child(index)
        proc.start()
        logger.info("worker_child_spawned: index=%d pid=%s", index, proc.pid)
        children.append(proc)

    try:
        while True:
            time.sleep(1.0)
            for idx, proc in enumerate(children, start=1):
                if proc.is_alive():
                    continue
                logger.warning(
                    "worker_child_exited: index=%d pid=%s exit_code=%s; restarting",
                    idx,
                    proc.pid,
                    proc.exitcode,
                )
                replacement = _spawn_worker_child(idx)
                replacement.start()
                logger.info("worker_child_spawned: index=%d pid=%s", idx, replacement.pid)
                children[idx - 1] = replacement
    except KeyboardInterrupt:
        logger.info("worker_supervisor_shutdown: terminating children")
    finally:
        for proc in children:
            if proc.is_alive():
                proc.terminate()
        for proc in children:
            proc.join(timeout=5.0)
            if proc.is_alive():
                logger.warning("worker_child_force_kill: pid=%s", proc.pid)
                proc.kill()
                proc.join(timeout=2.0)


if __name__ == "__main__":
    run_worker()
