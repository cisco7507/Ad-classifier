---
description: Replace Gradio with a custom dashboard
---

Replace Gradio with a custom dashboard

Steps:
1) Create pages:
   - Cluster overview (nodes up/down, active jobs)
   - Jobs table (filters, search)
   - Job detail (frames gallery, OCR text, scores, final record, export)
2) Implement polling strategy:
   - polling for pipeline jobs
   - incremental updates for agent jobs (poll /events or SSE/WebSocket)
3) Ensure dashboard calls only public API routes (no direct DB access).

Exit criteria:
- A job can be submitted and viewed fully in dashboard
