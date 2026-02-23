---
name: dashboard-contract
description: Defines the dashboard pages and how they consume cluster and job endpoints (polling/streaming).
---

# Dashboard Contract Skill

## Pages
- Cluster overview: nodes + up/down + active jobs
- Jobs table: filter/search/sort
- Job detail:
  - frames gallery
  - OCR text panel
  - vision scores (top matches)
  - final classification record
  - agent logs timeline (agent mode)
  - export CSV

## Data fetching rules
- Use /cluster/jobs for cluster-wide lists.
- Use /jobs/{id} and /jobs/{id}/result for detail.
- Use /jobs/{id}/events for agent mode incremental updates.

See resources/dashboard_pages.md and resources/events_transport.md.
