---
trigger: always_on
---

# Project Rules — Video Ad Classification Service

## Non-negotiables
- Preserve the *video ad classification behavior* of `combined.py` exactly; changes must be parity-tested.
- Do NOT implement audio gate logic, audio language ID, VAD, transcription, or audio-only pipelines.
- Do implement HA cluster, internal proxying, round-robin job distribution, dashboard aggregation, worker pool, and DB-backed queue patterns described in the LangId-mr README — adapted for video jobs.
- Every Gradio capability must be reachable via backend API endpoints (no hidden UI-only logic).

## Architecture guardrails
- Backend: FastAPI + background worker subsystem + DB-backed job queue.
- Use a “shared-nothing” cluster model:
  - Job IDs are prefixed with node name: `<node-name>-<uuid>`.
  - Any node can receive requests; job-specific routes proxy to owner node using `?internal=1`.
  - New job creation uses round-robin across healthy nodes; retries next healthy node if target down.
  - Cluster dashboard aggregates by fan-out to each node’s `/admin/jobs`.

## API surface parity requirements
The API must cover:
- Job submission from:
  - one-or-many URLs
  - local file paths / folder scan equivalents (server-side)
  - direct file upload
- Execution modes:
  - Standard Pipeline (concurrent workers)
  - ReACT Agent (sequential, supports incremental logs)
- Settings mirrored from UI (keep names stable):
  - categories optional input
  - provider/model selection
  - OCR engine + OCR mode
  - scan strategy (full vs tail)
  - allow-invent-categories override
  - enable agentic search
  - enable vision
  - context limit
  - pipeline concurrency
- Outputs:
  - per-job status, progress, logs (agent mode), artifacts (frames gallery), final result record
  - batch results listing
  - export results (CSV)

## Worker + DB rules
- Workers claim jobs transactionally; one job per worker at a time.
- Prefer SQLite WAL mode; set busy_timeout to reduce locking errors.
- Persist `result_json` atomically and keep artifacts path-stable.

## Implementation hygiene
- Create small modules; do not keep “one giant combined.py”.
- Add OpenAPI schemas for every endpoint.
- Add parity tests for at least 3 representative videos (short, long, OCR-heavy).
- Any behavioral change requires updating parity fixtures and documenting why.

## Code style
- Python 3.10+.
- Type hints required for new modules.
- Structured logging; never `print()` in server code.
- All config via env + optional `cluster_config.json`.