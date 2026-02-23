import os
import uuid
import datetime
import json
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from typing import List, Optional
from video_service.db.database import get_db, init_db
from video_service.app.models.job import JobResponse, JobStatus, JobSettings, UrlBatchRequest, FolderRequest, JobSettingsForm

app = FastAPI(title="Video Ad Classification Service")

NODE_NAME = os.environ.get("NODE_NAME", "node-a")

@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/health")
def health_check():
    return {"status": "ok", "node": NODE_NAME}

@app.get("/metrics")
def get_metrics():
    return {"jobs_processed": 0}

def _create_job(mode: str, settings: JobSettings) -> str:
    job_id = f"{NODE_NAME}-{uuid.uuid4()}"
    status = "queued"
    
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO jobs (id, status, mode, settings) VALUES (?, ?, ?, ?)",
            (job_id, status, mode, settings.model_dump_json())
        )
    return job_id

@app.post("/jobs/by-urls", response_model=List[JobResponse])
def create_job_urls(request: UrlBatchRequest):
    responses = []
    for url in request.urls:
        job_id = _create_job(request.mode, request.settings)
        # TODO: worker dispatch
        responses.append(JobResponse(job_id=job_id, status="queued"))
    return responses

@app.post("/jobs/by-folder", response_model=List[JobResponse])
def create_job_folder(request: FolderRequest):
    # Scan folder and create jobs here server-side
    responses = []
    if os.path.isdir(request.folder_path):
        for f in os.listdir(request.folder_path):
            if f.lower().endswith(('.mp4', '.mov')):
                job_id = _create_job(request.mode, request.settings)
                # TODO: add file_path tracking to DB and worker dispatch
                responses.append(JobResponse(job_id=job_id, status="queued"))
    return responses

@app.post("/jobs/upload", response_model=JobResponse)
def create_job_upload(
    mode: str = Form(...),
    settings_json: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        settings = JobSettings.model_validate_json(settings_json)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid settings JSON: {e}")
        
    job_id = _create_job(mode, settings)
    
    # TODO: save `file` securely to disk with job_id prefix, trigger worker
    
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
            mode=r['mode']
        ))
        
    return results

@app.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str):
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
        mode=row['mode']
    )

@app.get("/jobs/{job_id}/result")
def get_job_result(job_id: str):
    # TODO: Fetch final result schema from separate DB table or disk
    return {"message": "Stub result"}

@app.get("/jobs/{job_id}/artifacts")
def get_job_artifacts(job_id: str):
    # TODO: Fetch frame lists / visual inferences / nebula plot
    return {"message": "Stub artifacts"}

@app.get("/jobs/{job_id}/events")
def get_job_events(job_id: str):
    # TODO: Fetch inner monologue lines or progress lines
    return {"events": ["Stub event logger"]}

@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return {"status": "deleted"}

@app.get("/admin/jobs", response_model=List[JobStatus])
def get_admin_jobs():
    # Identical to /jobs for now, but will be hit by the cluster aggregator
    return get_jobs_recent()
