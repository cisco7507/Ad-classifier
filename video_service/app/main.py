import os
import uuid
import datetime
import json
import tempfile
import shutil
import httpx
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse
from typing import List, Optional
from video_service.db.database import get_db, init_db
from video_service.app.models.job import JobResponse, JobStatus, JobSettings, UrlBatchRequest, FolderRequest, JobSettingsForm, JobMode
from video_service.core.device import get_diagnostics
from video_service.core.cluster import cluster

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Video Ad Classification Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
NODE_NAME = cluster.self_name

@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/health")
def health_check():
    return {"status": "ok", "node": NODE_NAME}

@app.get("/cluster/nodes")
def cluster_nodes():
    return {"nodes": cluster.nodes, "status": cluster.node_status, "self": cluster.self_name}

@app.get("/cluster/jobs")
async def cluster_jobs():
    if not cluster.enabled:
        return get_admin_jobs()
    
    aggr = []
    async with httpx.AsyncClient() as client:
        for node, url in cluster.nodes.items():
            if not cluster.node_status.get(node): continue
            try:
                res = await client.get(f"{url}/admin/jobs?internal=1", timeout=cluster.internal_timeout)
                if res.status_code == 200: aggr.extend(res.json())
            except: pass
            
    aggr.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return aggr

@app.get("/diagnostics/device")
def device_diagnostics():
    return get_diagnostics()

@app.get("/metrics")
def get_metrics():
    conn = get_db()
    cur = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE status = 'completed'")
    count = cur.fetchone()['c']
    return {"jobs_processed": count}

def _create_job(mode: str, settings: JobSettings, url: str = None) -> str:
    job_id = f"{NODE_NAME}-{uuid.uuid4()}"
    status = "queued"
    
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO jobs (id, status, mode, settings, url, events) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, status, mode, settings.model_dump_json(), url, "[]")
        )
    return job_id

async def proxy_request(request: Request, target_url: str) -> Response:
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
                timeout=cluster.internal_timeout
            )
            return Response(content=res.content, status_code=res.status_code, headers=dict(res.headers))
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Proxy error: {e}")

@app.post("/jobs/by-urls", response_model=List[JobResponse])
async def create_job_urls(request: Request, body: UrlBatchRequest):
    if not request.query_params.get("internal"):
        target_node = cluster.select_rr_node()
        if not target_node: raise HTTPException(503, "No healthy nodes")
        if target_node != cluster.self_name:
            return await proxy_request(request, cluster.get_node_url(target_node))
            
    responses = []
    for url in body.urls:
        job_id = _create_job(body.mode.value, body.settings, url=url)
        responses.append(JobResponse(job_id=job_id, status="queued"))
    return responses

@app.post("/jobs/by-folder", response_model=List[JobResponse])
async def create_job_folder(req: Request, request: FolderRequest):
    if not req.query_params.get("internal"):
        target_node = cluster.select_rr_node()
        if not target_node: raise HTTPException(503, "No healthy nodes")
        if target_node != cluster.self_name:
            return await proxy_request(req, cluster.get_node_url(target_node))
            
    responses = []
    if os.path.isdir(request.folder_path):
        for f in os.listdir(request.folder_path):
            if f.lower().endswith(('.mp4', '.mov')):
                full_path = os.path.join(request.folder_path, f)
                job_id = _create_job(request.mode.value, request.settings, url=full_path)
                responses.append(JobResponse(job_id=job_id, status="queued"))
    return responses

def parse_settings(
    categories: str = Form(""),
    provider: str = Form("Gemini CLI"),
    model_name: str = Form("Gemini CLI Default"),
    ocr_engine: str = Form("EasyOCR"),
    ocr_mode: str = Form("🚀 Fast"),
    scan_mode: str = Form("Tail Only"),
    override: bool = Form(False),
    enable_search: bool = Form(True),
    enable_vision: bool = Form(True),
    context_size: int = Form(8192),
    workers: int = Form(2),
) -> JobSettings:
    return JobSettings(
        categories=categories,
        provider=provider,
        model_name=model_name,
        ocr_engine=ocr_engine,
        ocr_mode=ocr_mode,
        scan_mode=scan_mode,
        override=override,
        enable_search=enable_search,
        enable_vision=enable_vision,
        context_size=context_size,
        workers=workers
    )


@app.post("/jobs/upload", response_model=JobResponse)
async def create_job_upload(
    req: Request,
    mode: JobMode = Form(JobMode.pipeline),
    settings: JobSettings = Depends(parse_settings),
    file: UploadFile = File(...)
):
    if not req.query_params.get("internal"):
        target_node = cluster.select_rr_node()
        if not target_node: raise HTTPException(503, "No healthy nodes")
        if target_node != cluster.self_name:
            return await proxy_request(req, cluster.get_node_url(target_node))
            
    upload_dir = "/tmp/video_service_uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{uuid.uuid4()}_{file.filename}")
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    job_id = _create_job(mode.value, settings, url=file_path)
    return JobResponse(job_id=job_id, status="queued")


@app.get("/jobs", response_model=List[JobStatus])
def get_jobs_recent():
    conn = get_db()
    cur = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50")
    rows = cur.fetchall()
    
    results = []
    for r in rows:
        results.append(JobStatus(
            job_id=r['id'],
            status=r['status'],
            created_at=r['created_at'],
            updated_at=r['updated_at'],
            progress=r['progress'],
            error=r['error'],
            settings=JobSettings.model_validate_json(r['settings']) if r['settings'] else None,
            mode=r['mode'],
            url=r['url']
        ))
        
    return results

async def _maybe_proxy(req: Request, job_id: str):
    if req.query_params.get("internal"): return None
    
    parts = job_id.split("-")
    if len(parts) >= 2:
        owner = getattr(cluster, "self_name", "node-a")
        # Find prefix logic: job ID looks like node-a-UUID or custom-node-name-UUID
        # We need to extract everything before the LAST dash just in case name has dashes?
        # Standard: node_name-uuid. UUID has 4 dashes. So node name is everything before last 5 segments.
        # But safest: check against cluster.nodes.keys()
        target = None
        for node in cluster.nodes.keys():
            if job_id.startswith(f"{node}-"): 
                target = node
                break
                
        if target and target != cluster.self_name:
            url = cluster.get_node_url(target)
            if url: return await proxy_request(req, url)
    return None

@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(req: Request, job_id: str):
    proxy_res = await _maybe_proxy(req, job_id)
    if proxy_res: return proxy_res
    
    conn = get_db()
    cur = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
        
    return JobStatus(
        job_id=row['id'],
        status=row['status'],
        created_at=row['created_at'],
        updated_at=row['updated_at'],
        progress=row['progress'],
        error=row['error'],
        settings=JobSettings.model_validate_json(row['settings']) if row['settings'] else None,
        mode=row['mode'],
        url=row['url']
    )

@app.get("/jobs/{job_id}/result")
async def get_job_result(req: Request, job_id: str):
    p = await _maybe_proxy(req, job_id)
    if p: return p
    
    conn = get_db()
    cur = conn.execute("SELECT result_json FROM jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    if not row or not row['result_json']:
        return {"result": None}
    return {"result": json.loads(row['result_json'])}

@app.get("/jobs/{job_id}/artifacts")
async def get_job_artifacts(req: Request, job_id: str):
    p = await _maybe_proxy(req, job_id)
    if p: return p
    
    conn = get_db()
    cur = conn.execute("SELECT artifacts_json FROM jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    if not row or not row['artifacts_json']:
        return {"artifacts": None}
    return {"artifacts": json.loads(row['artifacts_json'])}

@app.get("/jobs/{job_id}/events")
async def get_job_events(req: Request, job_id: str):
    p = await _maybe_proxy(req, job_id)
    if p: return p
    
    conn = get_db()
    cur = conn.execute("SELECT events FROM jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    if not row or not row['events']:
        return {"events": []}
    return {"events": json.loads(row['events'])}

@app.delete("/jobs/{job_id}")
async def delete_job(req: Request, job_id: str):
    p = await _maybe_proxy(req, job_id)
    if p: return p
    
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return {"status": "deleted"}

@app.get("/admin/jobs", response_model=List[JobStatus])
def get_admin_jobs():
    return get_jobs_recent()
