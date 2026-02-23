# API Contract (Draft)

## Public
GET /health
GET /metrics

POST /jobs/by-urls
POST /jobs/by-folder
POST /jobs/upload

GET /jobs
GET /jobs/{job_id}
GET /jobs/{job_id}/result
GET /jobs/{job_id}/artifacts
GET /jobs/{job_id}/events
DELETE /jobs/{job_id}

## Cluster
GET /cluster/jobs
GET /cluster/nodes

## Local admin (node-only)
GET /admin/jobs
