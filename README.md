# Video Ad Classifier

An HA-capable video ad classification service. Classifies video advertisements into industry categories using local vision-language models (Ollama / qwen3-vl), EasyOCR, and an optional semantic search step.

---

## Quick Start (Local Dev)

```bash
# 1. Prerequisites:
#    - Python 3.11+, Node.js 20+, ffmpeg
#    - Ollama running with: ollama pull qwen3-vl:8b-instruct

git clone <repo> && cd Ad-classifier
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # edit as needed

# 2. Start API + worker
uvicorn video_service.app.main:app --port 8000 &
DATABASE_PATH=video_service.db python -m video_service.workers.worker &

# 3. Dashboard
cd frontend && npm install && npm run dev
# → http://localhost:5173
# → API docs: http://localhost:8000/docs
```

---

## Features

- **Pipeline mode** — parallel frame extraction → OCR → LLM classification
- **ReACT Agent mode** — sequential multi-step reasoning with incremental logs
- **HA Cluster** — round-robin job distribution across nodes, proxy-to-owner routing
- **Dashboard** — real-time job monitoring, copy job ID / result JSON, CSV export
- **Parity tests** — 23-test suite validating API output matches reference logic

---

## Architecture

```
Dashboard (React + Vite)
        │
        ▼ HTTP
┌──────────────────┐        ┌──────────────────┐
│ FastAPI node-a   │◀──────▶│ FastAPI node-b   │
│ (port 8000)      │        │ (port 8001)       │
│  round-robin     │        │  round-robin      │
│  proxy-to-owner  │        │  proxy-to-owner   │
└────────┬─────────┘        └────────┬──────────┘
         │ SQLite WAL               │ SQLite WAL
    video_service.db           db_b/video_service.db
         │                         │
    ┌────▼──────┐             ┌────▼──────┐
    │ Worker A  │             │ Worker B  │
    └───────────┘             └───────────┘
```

---

## Repository Structure

```
video_service/
  app/
    main.py              # FastAPI app (security, routing, metrics)
    models/job.py        # Pydantic models
  core/
    pipeline.py          # process_single_video (ported from combined.py)
    agent.py             # ReACT agent pipeline
    video_io.py          # frame extraction, yt-dlp integration
    llm_engine.py        # LLM provider abstraction
    cluster.py           # HA cluster config + RR + health checks
    security.py          # URL validation, path guard, upload size
    cleanup.py           # Background TTL cleanup
    device.py            # torch device detection
  db/database.py         # SQLite WAL setup
  workers/worker.py      # Job claiming + execution
frontend/
  src/
    pages/               # Overview, Jobs, JobDetail
    lib/api.ts           # Typed API client + CSV export
poc/combined.py          # Original reference implementation (do not modify)
tests/
  test_parity.py         # 23 parity tests
  fixtures/              # Test fixtures + goldens
scripts/
  capture_goldens.py     # Refresh reference outputs
  download_fixtures.py   # Download local test videos
docs/
  DEPLOYMENT.md          # Full deployment guide
  parity-tests.md        # Parity test documentation
  api-curl-guide.md      # API usage examples
```

---

## Running

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for full instructions covering:

- Local development
- Single-node production run
- Two-node cluster run
- Docker & docker-compose
- Configuration reference
- Security hardening
- Observability / metrics

---

## Testing

```bash
# Parity suite (requires API running + worker)
pytest tests/test_parity.py -q

# Fast structural tests only (no LLM required)
pytest tests/test_parity.py::TestFrameCount tests/test_parity.py::TestScanStrategyParity -v

# Refresh goldens after intentional behavior change
python scripts/capture_goldens.py --force
```

---

## Security Notes

- CORS: configure `CORS_ORIGINS` in `.env` for your dashboard domain
- Upload limit: `MAX_UPLOAD_MB` (default 500 MB)
- URL allowlist: `URL_HOST_ALLOWLIST` restricts URL-based job submissions
- Path traversal: `ALLOWED_FOLDER_ROOTS` restricts server-side folder scanning

---

## Rules & Guardrails

See [`.agents/rules.md`](.agents/rules.md) for non-negotiable architecture rules.
Key ones: never modify `poc/combined.py` behavior; all behavioral changes require golden refresh + commit message.
