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
