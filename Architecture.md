# Video Ad Classifier Architecture

## Runtime Topology
- `video_service.app.main` runs the FastAPI API server.
- `video_service.workers.worker` runs background job processing against the same SQLite schema.
- Cluster mode is configured by `cluster_config*.json`; each node owns and serves its local jobs through `/admin/jobs`, while `/cluster/jobs` aggregates across healthy nodes.

## Data and Storage
- Primary persistence is SQLite (`video_service.db.database`).
- If `DATABASE_PATH` is unset, the service now defaults to a node-specific DB filename:
  - `video_service_${NODE_NAME}.db`
  - This prevents local multi-node collisions when running with different `NODE_NAME` values.
- Cleanup logic (`video_service.core.cleanup`) uses the same resolved DB path as the DB module.
- Jobs table observability fields:
  - `stage TEXT`
  - `stage_detail TEXT`
  - `init_db()` performs automatic backward-compatible migration using `PRAGMA table_info(jobs)` + `ALTER TABLE` if columns are missing.
  - Existing rows are backfilled with:
    - `stage = COALESCE(stage, status, 'queued')`
    - `stage_detail = COALESCE(stage_detail, '')`
- Jobs table dashboard-summary fields:
  - `brand TEXT`
  - `category TEXT`
  - `category_id TEXT`
  - Added with backward-compatible startup migration and backfilled to empty strings when null.

## Category Mapping
- Category-ID lookup is loaded by `video_service.core.category_mapping`.
- CSV source path resolution:
  - `CATEGORY_CSV_PATH` env var if set.
  - Otherwise deterministic absolute default: `<repo>/video_service/data/categories.csv`.
- Required schema is explicit and strict:
  - `ID`
  - `Freewheel Industry Category`
- Loader behavior:
  - Strips/normalizes whitespace in both columns.
  - Builds `category_name -> ID` (`ID` as string).
  - On missing file/invalid schema/read failure, logs a `CRITICAL` and marks mapping disabled with `last_error`.
- Runtime mapper behavior:
  - `video_service.core.categories.CategoryMapper` initializes `SentenceTransformer("all-MiniLM-L6-v2")` once at startup.
  - Pre-computes taxonomy embeddings once (`self.category_embeddings`) and maps with cosine-similarity argmax.
  - API fallback guarantees non-empty category/category_id when mapping is enabled by mapping one of:
    - Suggested categories text
    - Predicted brand
    - OCR summary text

## API Endpoints (Ops/Diagnostics)
- Existing:
  - `GET /health`
  - `GET /cluster/nodes`
  - `GET /cluster/jobs`
  - `GET /diagnostics/device`
- Added:
  - `GET /diagnostics/category` (and legacy alias `GET /diagnostics/categories`)
    - `category_mapping_enabled`
    - `category_mapping_count`
    - `category_csv_path_used`
    - `last_error`

## Observability and Logging
- Centralized logging setup is in `video_service.core.logging_setup`.
- Log context is propagated with `contextvars`:
  - `job_id`
  - `stage`
  - `stage_detail`
- Worker uses context helpers:
  - `set_job_context(job_id)` at claim/start
  - `set_stage_context(stage, detail)` on each stage transition
- Default logging behavior:
  - app logs at `INFO` (or `LOG_LEVEL` override)
  - noisy libraries (`uvicorn`, `httpx`, `transformers`, `PIL`, etc.) forced to `WARNING` unless DEBUG.
- Log format includes:
  - timestamp
  - level
  - `job_id`
  - `stage`
  - logger name + message

## Job Stage Lifecycle
- Worker persists stage transitions directly to `jobs.stage` and `jobs.stage_detail`:
  - `claim`
  - `ingest`
  - `frame_extract`
  - `ocr`
  - `vision` (when enabled)
  - `llm`
  - `persist`
  - terminal: `completed` / `failed`
- Failures always set:
  - `status='failed'`
  - `stage='failed'`
  - `stage_detail` with concise error summary.
- Event trail:
  - stage transitions and agent events are appended to `jobs.events` with bounded history.

## Dashboard Contract (Jobs + Detail)
- `JobStatus` now exposes:
  - `stage`
  - `stage_detail`
  - `brand`
  - `category`
  - `category_id`
- `/jobs`, `/jobs/{job_id}`, `/admin/jobs`, and `/cluster/jobs` payloads carry stage fields.
- Jobs table UI shows:
  - status badge
  - compact stage
  - truncated stage detail with tooltip.
- Job detail UI shows:
  - current stage
  - stage detail
  - stage/event history (`/jobs/{job_id}/events`) for processing/completed/failed jobs.
  - in `agent` mode, a dedicated "Agent Scratchboard" panel renders full agent-thinking event payloads from the same events stream.

## Cluster Jobs Aggregation
- `GET /cluster/jobs` fan-outs to each healthy node’s `/admin/jobs?internal=1`.
- Aggregation now deduplicates by `job_id`.
- If duplicates differ, record with newest `updated_at` is kept.

## Job Result Mapping Behavior
- Category mapping follows `poc/combined.py` parity logic:
  - Embed raw category text, compute cosine similarity against taxonomy embeddings, and choose argmax.
- For unknown/empty raw category, service uses fallback text and still performs embedding mapping.
- Job results include mapping metadata:
  - `category_match_method="embeddings"`
  - `category_match_score=<float>`

## ReACT Vision Tooling
- ReACT (`video_service.core.agent`) now performs a ReACT-local SigLIP text-feature readiness check before exposing/executing `[TOOL: VISION]`.
- If cache is missing, ReACT attempts to lazily build `category_mapper.vision_text_features` from taxonomy prompts.
- This change is isolated to ReACT path and does not modify pipeline execution flow.
- ReACT inner-monologue stream now emits incremental deltas (thought/step/result chunks) instead of replaying the full accumulated memory each iteration.

## Search Toggle Contract
- Job settings now accept search toggle aliases for dashboard/API parity:
  - `enable_search` (existing)
  - `enable_web_search` (dashboard-facing alias)
  - `enable_agentic_search` (compat alias)
- Normalization resolves these to a single runtime boolean used by worker execution.
- Upload form parser accepts the same aliases and persists normalized settings in `jobs.settings`.

## Artifact Contract (Dashboard Tabs)
- Static artifact files are served via:
  - `GET /artifacts/<job_id>/...` (FastAPI `StaticFiles` mount)
- Worker materializes structured artifacts in `jobs.artifacts_json` at completion.
- `GET /jobs/{job_id}/artifacts` always returns normalized keys:
  - `latest_frames`: list of `{timestamp, label, url}`
  - `ocr_text`: `{text, lines, url}`
  - `vision_board`: `{image_url, plot_url, top_matches, metadata}`
  - `extras.events_url`: link to `/jobs/{job_id}/events`
- Backward compatibility:
  - endpoint still returns `{"artifacts": ...}` and now also mirrors normalized keys at top level for direct tab consumption.
