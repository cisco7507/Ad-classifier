# Parity Test Suite

Automated tests ensuring the FastAPI service output matches the reference behavior from `poc/combined.py` (via the extracted `video_service.core.*` modules).

---

## Quick Start

```bash
# 1. Activate virtualenv
source venv/bin/activate

# 2. Download local fixture videos
python scripts/download_fixtures.py

# 3. Start the API + workers (both nodes, or just one)
CLUSTER_CONFIG=cluster_config.json uvicorn video_service.app.main:app \
  --host 127.0.0.1 --port 8000 &
DATABASE_PATH=video_service.db python -m video_service.workers.worker &

# 4. Capture golden reference outputs
python scripts/capture_goldens.py

# 5. Run parity suite
pytest tests/test_parity.py -v
```

---

## Fixture Definitions

Fixtures live in **`tests/fixtures/parity_fixtures.json`**.

| ID              | Type       | Description                                                       |
| --------------- | ---------- | ----------------------------------------------------------------- |
| `short_url`     | URL        | Short ad video (~15s) — primary smoke test                        |
| `local_mp4`     | Local file | Same video downloaded to disk — tests file-path ingestion         |
| `scan_strategy` | URL        | Same video with `Full Scan` mode — tests scan strategy divergence |

### Adding a Fixture

1. Add an entry to `tests/fixtures/parity_fixtures.json`
2. If it's a `local` type, add a download mapping in `scripts/download_fixtures.py`
3. Run `python scripts/capture_goldens.py --fixture <new_id>`
4. Commit the new golden

---

## Golden Reference Files

Goldens live in **`tests/golden/<fixture_id>.json`**.

Each golden contains:

- `frame_count` — expected number of extracted frames (exact match)
- `frame_meta` — per-frame timestamps and type (informational)
- `ocr_has_text` — whether OCR found any text in the video
- `result.brand` — expected brand name (exact, case-insensitive)
- `result.category` — expected Freewheel industry category (exact, case-insensitive)
- `result.category_id` — expected category ID (exact)
- `result.confidence` — expected confidence (± 0.25 tolerance)

### Refreshing Goldens

Run this after an **intentional** behavioral change:

```bash
python scripts/capture_goldens.py --force
```

Then **document why** in the commit message:

```bash
git add tests/golden/
git commit -m "chore(parity): refresh goldens — reason: <what changed and why>"
```

> ⚠️ **Never silently refresh goldens** to fix a failing test. A golden change must be accompanied by a code comment or PR description explaining the behavioural delta.

---

## Tolerance Policy

| Field         | Tolerance     | Justification                                               |
| ------------- | ------------- | ----------------------------------------------------------- |
| `brand`       | None (exact)  | Deterministic string from LLM JSON; temperature=0.1         |
| `category`    | None (exact)  | Deterministic string from category mapper                   |
| `category_id` | None (exact)  | Integer ID lookup — pure deterministic                      |
| `confidence`  | ± 0.25        | LLM float; minor variation from sampling at low temperature |
| `reasoning`   | Not compared  | Free-form LLM prose — varies across runs by design          |
| `frame_count` | None (exact)  | Frame extraction is deterministic for a given video         |
| OCR text      | Presence only | OCR character output has minor layout variance              |

---

## Environment Variables

| Variable                      | Default                 | Description                        |
| ----------------------------- | ----------------------- | ---------------------------------- |
| `PARITY_API_URL`              | `http://127.0.0.1:8000` | Base URL of the API under test     |
| `PARITY_JOB_TIMEOUT`          | `300`                   | Seconds to wait for job completion |
| `PARITY_POLL_INTERVAL`        | `3`                     | Polling interval in seconds        |
| `PARITY_CONFIDENCE_TOLERANCE` | `0.25`                  | Allowed confidence delta           |

---

## CI Command

```bash
# Full parity suite (requires API running)
pytest tests/test_parity.py -q --tb=short

# Fast unit tests only (no API required)
pytest tests/ -q -m "not parity"

# Frame count + scan strategy (no LLM, no API)
pytest tests/test_parity.py::TestFrameCount tests/test_parity.py::TestScanStrategyParity -v
```

---

## Test Classes

| Class                    | What it tests                                            | Requires API         |
| ------------------------ | -------------------------------------------------------- | -------------------- |
| `TestAPIParity`          | Brand, category, category_id, confidence, field presence | ✅ Yes               |
| `TestOCRParity`          | OCR text presence propagates to reasoning                | ✅ Yes               |
| `TestScanStrategyParity` | Tail Only < Full Scan frame count                        | ❌ No (module-level) |
| `TestFrameCount`         | Frame extraction is deterministic                        | ❌ No (module-level) |
