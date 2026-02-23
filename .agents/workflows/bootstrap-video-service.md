---
description: Convert combined.py POC into a service repo skeleton (FastAPI + workers + dashboard contract)
---

Goal: convert combined.py POC into a service repo skeleton (FastAPI + workers + dashboard contract).

Steps:
1) Create folders:
   - video_service/app (FastAPI)
   - video_service/workers
   - video_service/core (ported combined.py logic)
   - dashboard/ (frontend)
2) Add config files:
   - .env.example
   - cluster_config.example.json
3) Create minimal endpoints:
   - GET /health
   - GET /metrics (stub)
4) Create DB + Job model skeleton:
   - statuses: queued, processing, completed, failed
5) Create a “hello job” path:
   - POST /jobs creates queued job, returns job_id
   - worker picks it up and marks completed

Exit criteria:
- `uvicorn` runs
- one job can be queued and completed end-to-end
