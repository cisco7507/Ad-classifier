---
name: worker-queue-sqlite
description: Implements DB-backed queue + worker claiming using SQLite WAL mode and atomic result persistence.
---

# Worker Queue (SQLite) Skill

## Requirements
- Transactional claim/update to avoid double-processing.
- WAL mode + busy_timeout.
- One job per worker process at a time.

## Included references
- resources/sqlite_wal_notes.md
- resources/job_claim_pattern.md
