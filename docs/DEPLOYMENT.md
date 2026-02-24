# Deployment Guide — Video Ad Classifier

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Local Development](#local-development)
4. [Single-Node Run](#single-node-run)
5. [Two-Node Cluster Run](#two-node-cluster-run)
6. [Dashboard Run](#dashboard-run)
7. [Docker (Single Node)](#docker-single-node)
8. [Docker (Two-Node Cluster)](#docker-two-node-cluster)
9. [Configuration Reference](#configuration-reference)
10. [Security Hardening](#security-hardening)
11. [Observability](#observability)
12. [Upgrading / Cleanup](#upgrading--cleanup)

---

## Architecture Overview

```
┌─────────────┐   HTTP    ┌──────────────────────────────────────────────────┐
│  Dashboard  │ ────────▶ │  node-a  :8000                                   │
│  (Vite/nginx│           │  ┌──────────────────┐                            │
│  port 5173) │           │  │  FastAPI          │◀── round-robin submit      │
└─────────────┘           │  │  + security mw    │─── proxy-to-owner         │
                          │  │  + cluster router │                            │
                          │  └────────┬─────────┘                            │
                          │           │                                       │
                          │    SQLite WAL (video_service.db)                  │
                          │           │                                       │
                          │  ┌────────▼─────────┐                            │
                          │  │  Worker           │                            │
                          │  │  (claims jobs,    │                            │
                          │  │   runs pipeline)  │                            │
                          │  └──────────────────┘                            │
                          └──────────────────────────────────────────────────┘

Two-node cluster adds node-b :8001 with its own DB + worker.
Round-robin distributes new jobs. Each node proxies job-specific GETs to the owner.
```

---

## Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) running locally with `qwen3-vl:8b-instruct` pulled:
  ```bash
  ollama pull qwen3-vl:8b-instruct
  ```
- Node.js 20+ (for dashboard dev)
- `ffmpeg` installed (for frame extraction)

---

## Local Development

```bash
# 1. Clone & create venv
git clone <repo>
cd Ad-classifier
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Copy environment
cp .env.example .env
# Edit .env as needed (NODE_NAME, PORT, etc.)

# 3. Download fixture videos (for parity tests)
python scripts/download_fixtures.py

# 4. Start API (single node, auto-creates DB)
uvicorn video_service.app.main:app --reload --port 8000

# 5. Start worker (separate terminal)
DATABASE_PATH=video_service.db python -m video_service.workers.worker

# 6. Start dashboard
cd frontend && npm install && npm run dev
```

Dashboard: http://localhost:5173  
API docs: http://localhost:8000/docs

---

## Single-Node Run

Minimal setup — one API server, one worker, no cluster config needed.

```bash
# Terminal 1 — API
NODE_NAME=node-a DATABASE_PATH=video_service.db \
  uvicorn video_service.app.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — Worker
DATABASE_PATH=video_service.db python -m video_service.workers.worker
```

Workers pick up queued jobs automatically. No cluster config file means the node
registers only itself (`cluster.enabled = False`), and no round-robin or proxying occurs.

---

## Two-Node Cluster Run

Requires two separate databases (one per node) and the cluster config files.

```bash
# Terminal 1 — node-a API
CLUSTER_CONFIG=cluster_config.json NODE_NAME=node-a DATABASE_PATH=video_service.db \
  uvicorn video_service.app.main:app --port 8000

# Terminal 2 — node-a worker
DATABASE_PATH=video_service.db python -m video_service.workers.worker

# Terminal 3 — node-b API
mkdir -p db_b
CLUSTER_CONFIG=cluster_config_b.json NODE_NAME=node-b DATABASE_PATH=db_b/video_service.db \
  uvicorn video_service.app.main:app --port 8001

# Terminal 4 — node-b worker
DATABASE_PATH=db_b/video_service.db python -m video_service.workers.worker
```

### How Routing Works

1. **New job submission** → round-robin selects the next healthy node → if not self, proxied via `?internal=1`
2. **Job status / result reads** → job ID prefix (`node-a-`, `node-b-`) identifies the owner node → proxied if needed
3. **Cluster dashboard fan-out** → `/cluster/jobs` calls `/admin/jobs?internal=1` on each healthy node and merges results
4. **Health loop** → background thread pings every node every 10 s; unhealthy nodes are skipped in round-robin

---

## Dashboard Run

```bash
cd frontend

# Development (hot-reload)
VITE_API_BASE_URL=http://localhost:8000 npm run dev

# Production build
VITE_API_BASE_URL=http://your-api-host:8000 npm run build
# Serve dist/ with nginx (see frontend/Dockerfile.frontend)
```

CORS: ensure `CORS_ORIGINS` in `.env` includes your dashboard origin.

---

## Docker (Single Node)

```bash
# Build
docker build -t ad-classifier-backend .

# Run API
docker run -d \
  -e NODE_NAME=node-a \
  -e DATABASE_PATH=/data/video_service.db \
  -e CORS_ORIGINS=http://localhost:5173 \
  -v $(pwd)/data:/data \
  -p 8000:8000 \
  ad-classifier-backend

# Run worker (same image, separate command)
docker run -d \
  -e DATABASE_PATH=/data/video_service.db \
  -v $(pwd)/data:/data \
  ad-classifier-backend \
  python -m video_service.workers.worker
```

### CUDA Variant

Change the `FROM` in `Dockerfile` to:

```dockerfile
FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime AS base
```

And install torch with CUDA extras:

```dockerfile
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

---

## Docker (Two-Node Cluster)

```bash
# Single-node (default)
docker-compose up backend-a worker-a dashboard

# Full two-node cluster
docker-compose --profile cluster up
```

The `cluster` Docker Compose profile activates `backend-b` and `worker-b`. Each node
gets its own named volume (`data-a`, `data-b`) so databases never share a file.

---

## Configuration Reference

All variables can be set in `.env` (copied from `.env.example`) or passed directly as environment variables.

| Variable                 | Default                        | Description                                        |
| ------------------------ | ------------------------------ | -------------------------------------------------- |
| `NODE_NAME`              | `node-a`                       | Node identity prefix for job IDs                   |
| `PORT`                   | `8000`                         | API server port                                    |
| `DATABASE_PATH`          | `video_service.db`             | SQLite file path                                   |
| `CLUSTER_CONFIG`         | `cluster_config.json`          | Cluster node definition file                       |
| `UPLOAD_DIR`             | `/tmp/video_service_uploads`   | Temp dir for uploaded videos                       |
| `ARTIFACTS_DIR`          | `/tmp/video_service_artifacts` | Persistent per-job artifacts                       |
| `CORS_ORIGINS`           | `http://localhost:5173,...`    | Comma-separated allowed dashboard origins          |
| `MAX_UPLOAD_MB`          | `500`                          | Upload size limit                                  |
| `URL_FETCH_TIMEOUT`      | `30`                           | Seconds before URL fetch times out                 |
| `URL_HOST_ALLOWLIST`     | _(empty)_                      | Comma-separated allowed hostnames for URL jobs     |
| `URL_HOST_DENYLIST`      | _(empty)_                      | Comma-separated blocked hostnames                  |
| `ALLOWED_FOLDER_ROOTS`   | _(empty)_                      | Comma-separated allowed base paths for folder jobs |
| `JOB_TTL_DAYS`           | `30`                           | Days before completed/failed jobs are pruned       |
| `CLEANUP_INTERVAL_HOURS` | `6`                            | How often cleanup runs                             |
| `CLEANUP_ENABLED`        | `true`                         | Enable/disable background cleanup                  |
| `LOG_LEVEL`              | `INFO`                         | Python log level                                   |

---

## Security Hardening

### URL Fetch Protection

- Only `http://` and `https://` schemes accepted
- Optional `URL_HOST_ALLOWLIST` restricts to known CDNs/domains
- `URL_HOST_DENYLIST` blocks internal/SSRF targets (e.g. `localhost,169.254.169.254`)
- Timeout (`URL_FETCH_TIMEOUT`) prevents hanging on slow servers

### Upload Size Limit

- `MAX_UPLOAD_MB` enforced on Content-Length header AND during streaming
- Files larger than the limit are rejected mid-stream; partial files are deleted

### Path Traversal

- `/jobs/by-folder` resolves all symlinks and checks against `ALLOWED_FOLDER_ROOTS`
- Relative paths and `../` traversals are rejected with HTTP 400/403

### CORS

- Default: localhost dashboard ports only
- Set `CORS_ORIGINS` to your production dashboard URL

### Internal Proxy Recursion

- All proxied requests include `?internal=1`
- Receiving nodes skip routing when `internal=1` is present — no infinite loops

---

## Observability

### Logs

All server and worker logs use Python's `logging` module with structured fields:

```
2026-02-24T09:00:00 INFO     video_service.app.main job_created: job_id=node-a-xxx mode=pipeline url=https://...
2026-02-24T09:00:30 INFO     video_service.workers.worker job_completed: job_id=node-a-xxx
```

### Health Endpoints

```bash
curl http://localhost:8000/health          # local node + DB check
curl http://localhost:8000/cluster/nodes   # all nodes + status
```

### Metrics

```bash
curl http://localhost:8000/metrics
# {
#   "jobs_queued": 0,
#   "jobs_processing": 1,
#   "jobs_completed": 42,
#   "jobs_failed": 2,
#   "jobs_submitted_this_process": 5,
#   "uptime_seconds": 3601,
#   "node": "node-a"
# }
```

---

## Upgrading / Cleanup

### Manual DB cleanup

```bash
# Remove jobs older than 30 days and orphaned artifacts
python -c "from video_service.core.cleanup import run_cleanup_once; print(run_cleanup_once())"
```

### Refresh parity goldens after intentional behavior change

```bash
python scripts/capture_goldens.py --force
git add tests/golden/
git commit -m "chore(parity): refresh goldens — reason: <why>"
```

### Run parity tests

```bash
pytest tests/test_parity.py -q
```
