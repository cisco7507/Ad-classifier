---
description: Implement DB-backed queue + workers
---

Goal: implement DB-backed queue + workers.

Steps:
1) Enable WAL mode and busy_timeout on DB connect.
2) Implement atomic claim:
   - SELECT next queued job
   - UPDATE status=processing if still queued
3) Worker executes one job:
   - runs either pipeline mode or agent mode
4) Persist:
   - OCR text
   - frames metadata + saved images
   - vision scores
   - final classification record
   - agent logs (if agent mode)

Exit criteria:
- N workers process N jobs concurrently without deadlocks