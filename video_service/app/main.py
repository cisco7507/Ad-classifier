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
import time as _time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from video_service.core.logging_setup import configure_logging
configure_logging()

from video_service.db.database import get_db, init_db
from video_service.app.models.job import (
    JobResponse, JobStatus, JobSettings,
    UrlBatchRequest, FolderRequest, FilePathRequest, JobMode,
)
from video_service.core.device import get_diagnostics
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
    start_cleanup_thread()
    logger.info("startup: ready (node=%s, cors_origins=%s)", NODE_NAME, CORS_ORIGINS)
    yield
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
        conn = get_db()
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
    conn = get_db()
    stats = {}
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


# ── Internal helpers ─────────────────────────────────────────────────────────

def _create_job(mode: str, settings: JobSettings, url: str = None) -> str:
    job_id = f"{NODE_NAME}-{uuid.uuid4()}"
    conn = get_db()
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
    workers: int = Form(1),
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
        context_size=context_size, workers=workers,
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

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [
        JobStatus(
            job_id=r["id"], status=r["status"],
            stage=row_value(r, "stage"), stage_detail=row_value(r, "stage_detail"),
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
    conn = get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    def row_value(r, key: str, default=None):
        return r[key] if key in r.keys() else default
    return JobStatus(
        job_id=row["id"], status=row["status"],
        stage=row_value(row, "stage"), stage_detail=row_value(row, "stage_detail"),
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
    conn = get_db()
    row = conn.execute("SELECT result_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row or not row["result_json"]:
        return {"result": None}
    return {"result": json.loads(row["result_json"])}


@app.get("/jobs/{job_id}/artifacts", tags=["jobs"])
async def get_job_artifacts(req: Request, job_id: str):
    proxy = await _maybe_proxy(req, job_id)
    if proxy:
        return proxy
    conn = get_db()
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
    conn = get_db()
    row = conn.execute("SELECT events FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row or not row["events"]:
        return {"events": []}
    return {"events": json.loads(row["events"])}


@app.delete("/jobs/{job_id}", tags=["jobs"])
async def delete_job(req: Request, job_id: str):
    proxy = await _maybe_proxy(req, job_id)
    if proxy:
        return proxy
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    logger.info("job_deleted: job_id=%s", job_id)
    return {"status": "deleted"}


# ── Admin aggregation ────────────────────────────────────────────────────────

@app.get("/admin/jobs", response_model=List[JobStatus], tags=["admin"])
def get_admin_jobs():
    """Per-node job list — called by cluster dashboard fan-out."""
    return _get_jobs_from_db()
