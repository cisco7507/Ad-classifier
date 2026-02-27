"""
video_service/app/main.py
==========================
FastAPI application — production-hardened.

Security additions
------------------
- CORS restricted to CORS_ORIGINS env var (default: localhost dashboard ports)
- URL validation on every /jobs/by-urls submission
- Path traversal guard on /jobs/by-folder
- Upload size limit (MAX_UPLOAD_MB env var, default 500 MB)
- Internal routing uses ?internal=1 (proxy recursion protection)

Observability additions
-----------------------
- Structured JSON logging via video_service.core.logging_setup
- /metrics endpoint with richer counters
- /health returns node + DB liveness
- /cluster/nodes shows per-node health with latency
"""

import os
import uuid
import json
import shutil
import logging
import mimetypes
import time as _time
from datetime import datetime, timezone
from collections import defaultdict
from contextlib import asynccontextmanager, closing
from typing import List, Optional
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from video_service.core.logging_setup import configure_logging
configure_logging()

from video_service.db.database import get_db, init_db
from video_service.app.models.job import (
    JobResponse, JobStatus, JobSettings,
    UrlBatchRequest, FolderRequest, FilePathRequest, BulkDeleteRequest, JobMode,
)
from video_service.core.device import get_diagnostics
from video_service.core.concurrency import get_concurrency_diagnostics
from video_service.core.cluster import cluster
from video_service.core.categories import category_mapper
from video_service.core.security import (
    validate_url, safe_folder_path, check_upload_size,
    MAX_UPLOAD_BYTES, MAX_UPLOAD_MB,
)
from video_service.core.cleanup import start_cleanup_thread

logger = logging.getLogger(__name__)

# ── In-memory counters (per-process; reset on restart) ───────────────────────
_counters: dict[str, int] = defaultdict(int)
_start_time = _time.time()

# ── CORS config ──────────────────────────────────────────────────────────────
_CORS_ORIGINS_RAW = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174"
)
CORS_ORIGINS: list[str] = [o.strip() for o in _CORS_ORIGINS_RAW.split(",") if o.strip()]

NODE_NAME = cluster.self_name
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/tmp/video_service_uploads")
ARTIFACTS_DIR = os.environ.get("ARTIFACTS_DIR", "/tmp/video_service_artifacts")
os.makedirs(ARTIFACTS_DIR, exist_ok=True)


# ── App lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Re-apply logging gates after server bootstrap to suppress noisy libs
    # even if another component touched logger levels/handlers.
    configure_logging(force=True)
    cluster.start_health_checks()
    logger.info("startup: initialising DB (node=%s)", NODE_NAME)
    init_db()
    _recover_stale_jobs_on_startup()
    from video_service.core.stale_recovery import (
        start_stale_recovery_thread,
        stop_stale_recovery,
    )
    start_stale_recovery_thread()
    start_cleanup_thread()

    from video_service.core.watcher import start_watcher, stop_watcher
    watcher_observer = start_watcher()

    # Lazy import avoids pulling worker-side heavy deps during module import.
    from video_service.workers.embedded import (
        start as start_embedded_workers,
        shutdown as shutdown_embedded_workers,
    )
    worker_count = start_embedded_workers()
    if worker_count:
        logger.info("startup: %d embedded worker(s) active", worker_count)

    logger.info("startup: ready (node=%s, cors_origins=%s)", NODE_NAME, CORS_ORIGINS)
    try:
        yield
    finally:
        stop_watcher(watcher_observer)
        stop_stale_recovery()
        shutdown_embedded_workers()
        logger.info("shutdown: node=%s", NODE_NAME)


app = FastAPI(
    title="Video Ad Classification Service",
    version="1.0.0",
    description="HA cluster of workers that classify video advertisements.",
    lifespan=lifespan,
)
app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_DIR), name="artifacts")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ── Health & diagnostics ─────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
def health_check():
    """Local node health. Checks DB is reachable."""
    try:
        with closing(get_db()) as conn:
            conn.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception as exc:
        logger.error("health: DB check failed: %s", exc)
        db_ok = False

    status = "ok" if db_ok else "degraded"
    code   = 200  if db_ok else 503
    return JSONResponse({"status": status, "node": NODE_NAME, "db": db_ok}, status_code=code)


@app.get("/cluster/nodes", tags=["ops"])
async def cluster_nodes():
    """Returns all configured nodes + their last-known health state."""
    return {
        "nodes": cluster.nodes,
        "status": cluster.node_status,
        "self": cluster.self_name,
    }


@app.get("/ollama/models", tags=["ops"])
async def list_ollama_models():
    """Return locally available Ollama models; [] when Ollama is unreachable."""
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{ollama_host}/api/tags", timeout=5.0)
            if res.status_code == 200:
                payload = res.json()
                models = payload.get("models", [])
                return [
                    {
                        "name": model.get("name", ""),
                        "size": model.get("size"),
                        "modified_at": model.get("modified_at"),
                    }
                    for model in models
                    if isinstance(model, dict) and model.get("name")
                ]
    except Exception as exc:
        logger.warning("ollama_models: unreachable: %s", exc)
    return []


@app.get("/cluster/jobs", tags=["ops"])
async def cluster_jobs():
    """Fan out /admin/jobs to all healthy nodes and merge."""
    if not cluster.enabled:
        return _get_jobs_from_db()

    aggr: list = []
    async with httpx.AsyncClient() as client:
        for node, url in cluster.nodes.items():
            if not cluster.node_status.get(node):
                continue
            try:
                res = await client.get(
                    f"{url}/admin/jobs?internal=1",
                    timeout=cluster.internal_timeout
                )
                if res.status_code == 200:
                    aggr.extend(res.json())
            except Exception as exc:
                logger.warning("cluster_jobs: node %s unreachable: %s", node, exc)

    deduped = _dedupe_jobs_by_id(aggr)
    if len(deduped) != len(aggr):
        logger.info(
            "cluster_jobs: deduped duplicate rows total=%d unique=%d",
            len(aggr),
            len(deduped),
        )
    return deduped


@app.get("/diagnostics/device", tags=["ops"])
def device_diagnostics():
    return get_diagnostics()


@app.get("/diagnostics/concurrency", tags=["ops"])
def concurrency_diagnostics():
    return get_concurrency_diagnostics()


@app.get("/diagnostics/watcher", tags=["ops"])
def watcher_diagnostics():
    from video_service.core.watcher import get_watcher_diagnostics

    return get_watcher_diagnostics()


def _get_category_mapping_diagnostics():
    return category_mapper.get_diagnostics()


@app.get("/diagnostics/category", tags=["ops"])
def category_mapping_diagnostics():
    return _get_category_mapping_diagnostics()


@app.get("/diagnostics/categories", tags=["ops"])
def category_mapping_diagnostics_legacy():
    return _get_category_mapping_diagnostics()


@app.get("/metrics", tags=["ops"])
def get_metrics():
    """Basic prometheus-style counters (text format available via Accept header)."""
    stats = {}
    with closing(get_db()) as conn:
        for status in ("queued", "processing", "completed", "failed"):
            row = conn.execute(
                "SELECT COUNT(*) as c FROM jobs WHERE status = ?", (status,)
            ).fetchone()
            stats[f"jobs_{status}"] = row["c"]

    return {
        **stats,
        "jobs_submitted_this_process": _counters["submitted"],
        "uptime_seconds": round(_time.time() - _start_time),
        "node": NODE_NAME,
    }


@app.get("/analytics", tags=["analytics"])
def get_analytics():
    with closing(get_db()) as conn:
        top_brands = conn.execute(
            """
            SELECT brand, COUNT(*) as count
            FROM job_stats
            WHERE status = 'completed'
              AND TRIM(COALESCE(brand, '')) != ''
              AND LOWER(TRIM(brand)) NOT IN ('unknown', 'none', 'n/a')
            GROUP BY brand
            ORDER BY count DESC
            LIMIT 20
            """
        ).fetchall()

        categories = conn.execute(
            """
            SELECT category, COUNT(*) as count
            FROM job_stats
            WHERE status = 'completed'
              AND TRIM(COALESCE(category, '')) != ''
              AND LOWER(TRIM(category)) NOT IN ('unknown', 'none', 'n/a')
            GROUP BY category
            ORDER BY count DESC
            LIMIT 25
            """
        ).fetchall()

        avg_duration_by_mode = conn.execute(
            """
            SELECT mode, AVG(duration_seconds) as avg_dur, COUNT(*) as count
            FROM job_stats
            WHERE status = 'completed'
              AND duration_seconds IS NOT NULL
            GROUP BY mode
            ORDER BY count DESC
            """
        ).fetchall()

        avg_duration_by_scan = conn.execute(
            """
            SELECT scan_mode, AVG(duration_seconds) as avg_dur, COUNT(*) as count
            FROM job_stats
            WHERE status = 'completed'
              AND duration_seconds IS NOT NULL
            GROUP BY scan_mode
            ORDER BY count DESC
            """
        ).fetchall()

        daily_outcomes = conn.execute(
            """
            SELECT DATE(completed_at) as day, status, COUNT(*) as count
            FROM job_stats
            GROUP BY day, status
            ORDER BY day
            """
        ).fetchall()

        providers = conn.execute(
            """
            SELECT provider, COUNT(*) as count
            FROM job_stats
            WHERE status = 'completed'
              AND TRIM(COALESCE(provider, '')) != ''
            GROUP BY provider
            ORDER BY count DESC
            """
        ).fetchall()

        totals = conn.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
                   AVG(CASE WHEN status='completed' THEN duration_seconds END) as avg_duration
            FROM job_stats
            """
        ).fetchone()

    def _round_or_none(value):
        return round(value, 1) if value is not None else None

    return {
        "top_brands": [{"brand": r["brand"], "count": r["count"]} for r in top_brands],
        "categories": [{"category": r["category"], "count": r["count"]} for r in categories],
        "avg_duration_by_mode": [
            {
                "mode": r["mode"] or "unknown",
                "avg_duration": _round_or_none(r["avg_dur"]),
                "count": r["count"],
            }
            for r in avg_duration_by_mode
        ],
        "avg_duration_by_scan": [
            {
                "scan_mode": r["scan_mode"] or "unknown",
                "avg_duration": _round_or_none(r["avg_dur"]),
                "count": r["count"],
            }
            for r in avg_duration_by_scan
        ],
        "daily_outcomes": [
            {"day": r["day"], "status": r["status"], "count": r["count"]}
            for r in daily_outcomes
        ],
        "providers": [{"provider": r["provider"], "count": r["count"]} for r in providers],
        "totals": {
            "total": totals["total"] if totals else 0,
            "completed": totals["completed"] if totals and totals["completed"] is not None else 0,
            "failed": totals["failed"] if totals and totals["failed"] is not None else 0,
            "avg_duration": _round_or_none(totals["avg_duration"] if totals else None),
        },
    }


# ── Internal helpers ─────────────────────────────────────────────────────────

def _create_job(mode: str, settings: JobSettings, url: str = None) -> str:
    job_id = f"{NODE_NAME}-{uuid.uuid4()}"
    with closing(get_db()) as conn:
        with conn:
            conn.execute(
                "INSERT INTO jobs (id, status, stage, stage_detail, mode, settings, url, events) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    "queued",
                    "queued",
                    "waiting for worker claim",
                    mode,
                    settings.model_dump_json(),
                    url,
                    "[]",
                ),
            )
    _counters["submitted"] += 1
    logger.info("job_created: job_id=%s mode=%s url=%s", job_id, mode, url)
    return job_id


def _default_job_artifacts(job_id: str) -> dict:
    return {
        "latest_frames": [],
        "ocr_text": {
            "text": "",
            "lines": [],
            "url": None,
        },
        "vision_board": {
            "image_url": None,
            "plot_url": None,
            "top_matches": [],
            "metadata": {},
        },
        "extras": {
            "events_url": f"/jobs/{job_id}/events",
        },
    }


def _normalize_job_artifacts(job_id: str, artifacts: Optional[dict]) -> dict:
    payload = _default_job_artifacts(job_id)
    if not isinstance(artifacts, dict):
        return payload

    payload["latest_frames"] = artifacts.get("latest_frames") or []

    ocr_payload = artifacts.get("ocr_text")
    if isinstance(ocr_payload, dict):
        payload["ocr_text"]["text"] = ocr_payload.get("text") or ""
        payload["ocr_text"]["lines"] = ocr_payload.get("lines") or []
        payload["ocr_text"]["url"] = ocr_payload.get("url")
    elif isinstance(ocr_payload, str):
        payload["ocr_text"]["text"] = ocr_payload
        payload["ocr_text"]["lines"] = [line for line in ocr_payload.splitlines() if line.strip()]

    vision_payload = artifacts.get("vision_board")
    if isinstance(vision_payload, dict):
        payload["vision_board"]["image_url"] = vision_payload.get("image_url")
        payload["vision_board"]["plot_url"] = vision_payload.get("plot_url")
        payload["vision_board"]["top_matches"] = vision_payload.get("top_matches") or []
        payload["vision_board"]["metadata"] = vision_payload.get("metadata") or {}

    extras = artifacts.get("extras")
    if isinstance(extras, dict):
        payload["extras"].update(extras)

    for key, value in artifacts.items():
        if key not in payload:
            payload[key] = value
    return payload


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


def _recover_stale_jobs_on_startup() -> int:
    """Reset any jobs left in processing state from a previous crash/restart."""
    with closing(get_db()) as conn:
        candidates = conn.execute(
            "SELECT id FROM jobs WHERE status = 'processing'"
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
                    stage_detail = 'recovered after restart',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                """,
                tuple(job_ids),
            )
            for job_id in job_ids:
                _append_recovery_event(conn, job_id, "recovered after process restart")

    logger.info(
        "startup_recovery: reset %d orphaned processing jobs to queued",
        len(job_ids),
    )
    return len(job_ids)


def _resolve_enable_web_search(
    enable_search: bool,
    enable_web_search: Optional[bool],
    enable_agentic_search: Optional[bool],
) -> bool:
    if enable_web_search is not None:
        return bool(enable_web_search)
    if enable_agentic_search is not None:
        return bool(enable_agentic_search)
    return bool(enable_search)


async def _proxy_request(request: Request, target_url: str) -> Response:
    """Forward a request to another cluster node, adding ?internal=1."""
    async with httpx.AsyncClient() as client:
        body = await request.body()
        headers = dict(request.headers)
        headers.pop("host", None)
        try:
            res = await client.request(
                method=request.method,
                url=f"{target_url}{request.url.path}?internal=1",
                content=body,
                headers=headers,
                timeout=cluster.internal_timeout,
            )
            return Response(content=res.content, status_code=res.status_code, headers=dict(res.headers))
        except Exception as exc:
            logger.error("proxy error → %s: %s", target_url, exc)
            raise HTTPException(status_code=503, detail=f"Proxy error: {exc}")


async def _maybe_proxy(req: Request, job_id: str) -> Response | None:
    """If the job belongs to another node, proxy the request there."""
    if req.query_params.get("internal"):
        return None
    target = None
    for node in cluster.nodes:
        if job_id.startswith(f"{node}-"):
            target = node
            break
    if target and target != cluster.self_name:
        url = cluster.get_node_url(target)
        if url:
            return await _proxy_request(req, url)
    return None


def _rr_or_raise() -> str:
    """Select a node via round-robin or raise 503."""
    node = cluster.select_rr_node()
    if not node:
        raise HTTPException(503, "No healthy nodes available")
    return node


# ── Job submission endpoints ─────────────────────────────────────────────────

@app.post("/jobs/by-urls", response_model=List[JobResponse], tags=["jobs"])
async def create_job_urls(request: Request, body: UrlBatchRequest):
    if not request.query_params.get("internal"):
        target = _rr_or_raise()
        if target != cluster.self_name:
            return await _proxy_request(request, cluster.get_node_url(target))

    responses = []
    for url in body.urls:
        safe_url = validate_url(url)
        job_id = _create_job(body.mode.value, body.settings, url=safe_url)
        responses.append(JobResponse(job_id=job_id, status="queued"))
    return responses


@app.post("/jobs/by-folder", response_model=List[JobResponse], tags=["jobs"])
async def create_job_folder(req: Request, request: FolderRequest):
    if not req.query_params.get("internal"):
        target = _rr_or_raise()
        if target != cluster.self_name:
            return await _proxy_request(req, cluster.get_node_url(target))

    safe_dir = safe_folder_path(request.folder_path)
    responses = []
    for fname in os.listdir(safe_dir):
        ext = os.path.splitext(fname)[1].lower()
        if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}:
            full_path = os.path.join(safe_dir, fname)
            job_id = _create_job(request.mode.value, request.settings, url=full_path)
            responses.append(JobResponse(job_id=job_id, status="queued"))
    return responses


@app.post("/jobs/by-filepath", response_model=JobResponse, tags=["jobs"])
async def create_job_filepath(req: Request, request: FilePathRequest):
    if not req.query_params.get("internal"):
        target = _rr_or_raise()
        if target != cluster.self_name:
            return await _proxy_request(req, cluster.get_node_url(target))

    file_path = (request.file_path or "").strip()
    if not file_path:
        raise HTTPException(status_code=400, detail="Empty file path")
    job_id = _create_job(request.mode.value, request.settings, url=file_path)
    return JobResponse(job_id=job_id, status="queued")


def _parse_settings(
    categories: str = Form(""),
    provider: str = Form("Ollama"),
    model_name: str = Form("qwen3-vl:8b-instruct"),
    ocr_engine: str = Form("EasyOCR"),
    ocr_mode: str = Form("🚀 Fast"),
    scan_mode: str = Form("Tail Only"),
    override: bool = Form(False),
    enable_search: bool = Form(False),
    enable_web_search: Optional[bool] = Form(None),
    enable_agentic_search: Optional[bool] = Form(None),
    enable_vision: bool = Form(False),
    context_size: int = Form(8192),
) -> JobSettings:
    resolved_search = _resolve_enable_web_search(
        enable_search=enable_search,
        enable_web_search=enable_web_search,
        enable_agentic_search=enable_agentic_search,
    )
    return JobSettings(
        categories=categories, provider=provider, model_name=model_name,
        ocr_engine=ocr_engine, ocr_mode=ocr_mode, scan_mode=scan_mode,
        override=override,
        enable_search=resolved_search,
        enable_web_search=resolved_search,
        enable_agentic_search=resolved_search,
        enable_vision=enable_vision,
        context_size=context_size,
    )


@app.post("/jobs/upload", response_model=JobResponse, tags=["jobs"])
async def create_job_upload(
    req: Request,
    mode: JobMode = Form(JobMode.pipeline),
    settings: JobSettings = Depends(_parse_settings),
    file: UploadFile = File(...),
):
    """
    Direct file upload endpoint.
    NOTE: multipart bodies cannot be re-streamed by the proxy, so this
    endpoint always processes locally (internal=1 behaviour).
    Clients should POST directly to the node they want to own the job
    (or always use ?internal=1 to skip routing).
    """
    # Enforce upload size
    content_length = req.headers.get("content-length")
    check_upload_size(int(content_length) if content_length else None)

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_filename = f"{uuid.uuid4()}_{os.path.basename(file.filename or 'upload.mp4')}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    # Stream with size guard
    written = 0
    try:
        with open(file_path, "wb") as buf:
            while chunk := await file.read(1 << 20):  # 1 MB chunks
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    os.remove(file_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds {MAX_UPLOAD_MB:.0f} MB limit"
                    )
                buf.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("upload_write_error: %s", exc)
        raise HTTPException(500, "Failed to save uploaded file")

    job_id = _create_job(mode.value, settings, url=file_path)
    return JobResponse(job_id=job_id, status="queued")


# ── Job read endpoints ───────────────────────────────────────────────────────

def _get_jobs_from_db(limit: int = 100) -> list:
    def row_value(r, key: str, default=None):
        return r[key] if key in r.keys() else default

    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        JobStatus(
            job_id=r["id"], status=r["status"],
            stage=row_value(r, "stage"), stage_detail=row_value(r, "stage_detail"),
            duration_seconds=row_value(r, "duration_seconds"),
            created_at=r["created_at"], updated_at=r["updated_at"],
            progress=r["progress"], error=row_value(r, "error"),
            settings=JobSettings.model_validate_json(r["settings"]) if r["settings"] else None,
            mode=row_value(r, "mode"), url=row_value(r, "url"),
            brand=row_value(r, "brand"), category=row_value(r, "category"), category_id=row_value(r, "category_id"),
        )
        for r in rows
    ]


def _dedupe_jobs_by_id(jobs: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for job in jobs:
        job_id = job.get("job_id")
        if not job_id:
            continue
        current = deduped.get(job_id)
        incoming_updated = job.get("updated_at") or ""
        current_updated = (current or {}).get("updated_at") or ""
        if current is None or incoming_updated > current_updated:
            deduped[job_id] = job

    return sorted(deduped.values(), key=lambda x: x.get("created_at", ""), reverse=True)


@app.get("/jobs", response_model=List[JobStatus], tags=["jobs"])
def get_jobs_recent():
    return _get_jobs_from_db()


@app.get("/jobs/{job_id}", response_model=JobStatus, tags=["jobs"])
async def get_job(req: Request, job_id: str):
    proxy = await _maybe_proxy(req, job_id)
    if proxy:
        return proxy
    with closing(get_db()) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    def row_value(r, key: str, default=None):
        return r[key] if key in r.keys() else default
    return JobStatus(
        job_id=row["id"], status=row["status"],
        stage=row_value(row, "stage"), stage_detail=row_value(row, "stage_detail"),
        duration_seconds=row_value(row, "duration_seconds"),
        created_at=row["created_at"], updated_at=row["updated_at"],
        progress=row["progress"], error=row_value(row, "error"),
        settings=JobSettings.model_validate_json(row["settings"]) if row["settings"] else None,
        mode=row_value(row, "mode"), url=row_value(row, "url"),
        brand=row_value(row, "brand"), category=row_value(row, "category"), category_id=row_value(row, "category_id"),
    )


@app.get("/jobs/{job_id}/result", tags=["jobs"])
async def get_job_result(req: Request, job_id: str):
    proxy = await _maybe_proxy(req, job_id)
    if proxy:
        return proxy
    with closing(get_db()) as conn:
        row = conn.execute("SELECT result_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row or not row["result_json"]:
        return {"result": None}
    return {"result": json.loads(row["result_json"])}


@app.get("/jobs/{job_id}/video", tags=["jobs"])
async def stream_job_video(req: Request, job_id: str):
    """Stream source video for a job. Serves local files only."""
    proxy = await _maybe_proxy(req, job_id)
    if proxy:
        return proxy

    with closing(get_db()) as conn:
        row = conn.execute("SELECT url FROM jobs WHERE id = ?", (job_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    source_url = (row["url"] or "").strip()
    if not source_url:
        raise HTTPException(status_code=404, detail="Source video not configured")

    if source_url.startswith(("http://", "https://")):
        return JSONResponse({"type": "remote", "url": source_url})

    try:
        video_path = Path(source_url).expanduser().resolve()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid video path: {exc}") from exc

    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Source video file not found on server")

    media_type = mimetypes.guess_type(str(video_path))[0] or "video/mp4"
    return FileResponse(path=str(video_path), media_type=media_type, filename=video_path.name)


@app.get("/jobs/{job_id}/artifacts", tags=["jobs"])
async def get_job_artifacts(req: Request, job_id: str):
    proxy = await _maybe_proxy(req, job_id)
    if proxy:
        return proxy
    with closing(get_db()) as conn:
        row = conn.execute("SELECT artifacts_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row or not row["artifacts_json"]:
        payload = _default_job_artifacts(job_id)
    else:
        try:
            parsed = json.loads(row["artifacts_json"])
        except Exception:
            parsed = None
        payload = _normalize_job_artifacts(job_id, parsed)
    return {"artifacts": payload, **payload}


@app.get("/jobs/{job_id}/events", tags=["jobs"])
async def get_job_events(req: Request, job_id: str):
    proxy = await _maybe_proxy(req, job_id)
    if proxy:
        return proxy
    with closing(get_db()) as conn:
        row = conn.execute("SELECT events FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row or not row["events"]:
        return {"events": []}
    return {"events": json.loads(row["events"])}


@app.delete("/jobs/{job_id}", tags=["jobs"])
async def delete_job(req: Request, job_id: str):
    proxy = await _maybe_proxy(req, job_id)
    if proxy:
        return proxy
    with closing(get_db()) as conn:
        with conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    logger.info("job_deleted: job_id=%s", job_id)
    return {"status": "deleted"}


@app.post("/jobs/bulk-delete", tags=["jobs"])
async def bulk_delete_jobs(body: BulkDeleteRequest):
    """Delete multiple jobs from local storage; skips IDs that don't exist."""
    if not body.job_ids:
        raise HTTPException(status_code=400, detail="No job IDs provided")
    if len(body.job_ids) > 500:
        raise HTTPException(status_code=400, detail="Too many IDs (max 500)")

    deleted = 0
    with closing(get_db()) as conn:
        with conn:
            for job_id in body.job_ids:
                cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                deleted += cursor.rowcount

    logger.info("bulk_delete: requested=%d deleted=%d", len(body.job_ids), deleted)
    return {"status": "deleted", "requested": len(body.job_ids), "deleted": deleted}


# ── Admin aggregation ────────────────────────────────────────────────────────

@app.get("/admin/jobs", response_model=List[JobStatus], tags=["admin"])
def get_admin_jobs():
    """Per-node job list — called by cluster dashboard fan-out."""
    return _get_jobs_from_db()
