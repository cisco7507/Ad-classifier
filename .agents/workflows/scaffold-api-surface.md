---
description: Scaffold the full API to match Gradio functionality
---

# /scaffold-api-surface

Goal: scaffold the full API to match Gradio functionality.

Steps:
1) Write an API contract (endpoints + request/response schemas).
2) Add endpoints:
   - POST /jobs/by-urls (batch)
   - POST /jobs/by-folder (server-side folder scan)
   - POST /jobs/upload (file upload)
   - GET /jobs (recent)
   - GET /jobs/{id}
   - GET /jobs/{id}/result
   - GET /jobs/{id}/artifacts
   - GET /jobs/{id}/events (agent logs via polling or streaming)
   - DELETE /jobs/{id}
   - GET /export.csv (optional; local-node export)
3) Ensure every request includes settings mirrored from UI.

Exit criteria:
- OpenAPI shows all endpoints
- Stub responses compile and run
