# Video Ad Classifier — API curl Guide

Complete reference for submitting and managing jobs via the REST API.

## Base URLs

| Node   | URL                     |
| ------ | ----------------------- |
| node-a | `http://127.0.0.1:8000` |
| node-b | `http://127.0.0.1:8001` |

You can send requests to **either** node; the cluster's round-robin logic will automatically route them to the healthiest node.

---

## Settings Reference

Every job submission accepts a `settings` object (JSON body) or individual form fields (multipart upload). All fields have defaults and are optional.

| Field           | Type   | Default                | Description                                                                 |
| --------------- | ------ | ---------------------- | --------------------------------------------------------------------------- |
| `categories`    | string | `""`                   | Comma-separated list of ad categories to detect. Empty = use built-in list. |
| `provider`      | string | `"Gemini CLI"`         | LLM provider. Options: `"Gemini CLI"`, `"OpenAI"`, `"Anthropic"`            |
| `model_name`    | string | `"Gemini CLI Default"` | Model name within the provider.                                             |
| `ocr_engine`    | string | `"EasyOCR"`            | OCR backend. Options: `"EasyOCR"`, `"Tesseract"`                            |
| `ocr_mode`      | string | `"🚀 Fast"`            | OCR scan density. Options: `"🚀 Fast"`, `"🔍 Thorough"`                     |
| `scan_mode`     | string | `"Tail Only"`          | Frame sampling strategy. Options: `"Tail Only"`, `"Full Scan"`              |
| `override`      | bool   | `false`                | If `true`, re-classify even if a cached result exists.                      |
| `enable_search` | bool   | `true`                 | Enable web search augmentation during classification.                       |
| `enable_vision` | bool   | `true`                 | Enable vision/frame analysis.                                               |
| `context_size`  | int    | `8192`                 | LLM context window token limit.                                             |
| `workers`       | int    | `2`                    | Worker parallelism for pipeline mode.                                       |

**Mode** (top-level, not inside `settings`):

| Value        | Description                                                 |
| ------------ | ----------------------------------------------------------- |
| `"pipeline"` | Concurrent workers — faster, ideal for batches.             |
| `"agent"`    | Sequential ReACT agent — slower, supports incremental logs. |

---

## Endpoints

### Health & Cluster

```bash
# Health check — returns node name
curl http://127.0.0.1:8000/health

# List cluster nodes and their status
curl http://127.0.0.1:8000/cluster/nodes

# Aggregated job list across ALL cluster nodes
curl http://127.0.0.1:8000/cluster/jobs

# Device / GPU diagnostics
curl http://127.0.0.1:8000/diagnostics/device

# Job count metrics
curl http://127.0.0.1:8000/metrics
```

---

## Job Submission

### 1. Submit URLs (Batch)

**Endpoint:** `POST /jobs/by-urls`

Submit one or more video URLs for classification in a single request. Returns a list of job IDs.

#### Minimal example (all defaults)

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "urls": ["https://example.com/video.mp4"],
    "settings": {}
  }'
```

#### Full example — Pipeline mode, Gemini CLI, EasyOCR Fast, Tail Only

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "urls": [
      "https://example.com/ad1.mp4",
      "https://example.com/ad2.mp4"
    ],
    "settings": {
      "categories": "Cars, Insurance, Finance",
      "provider": "Gemini CLI",
      "model_name": "Gemini CLI Default",
      "ocr_engine": "EasyOCR",
      "ocr_mode": "🚀 Fast",
      "scan_mode": "Tail Only",
      "override": false,
      "enable_search": true,
      "enable_vision": true,
      "context_size": 8192,
      "workers": 4
    }
  }'
```

#### Agent mode (incremental logs)

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "agent",
    "urls": ["https://example.com/ad.mp4"],
    "settings": {
      "provider": "Gemini CLI",
      "model_name": "Gemini CLI Default",
      "enable_search": true,
      "enable_vision": true,
      "context_size": 16384
    }
  }'
```

#### Full scan (instead of tail only)

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "urls": ["https://example.com/long_ad.mp4"],
    "settings": {
      "scan_mode": "Full Scan",
      "ocr_mode": "🔍 Thorough"
    }
  }'
```

#### Thorough OCR with Tesseract

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "urls": ["https://example.com/ocr_heavy.mp4"],
    "settings": {
      "ocr_engine": "Tesseract",
      "ocr_mode": "🔍 Thorough",
      "scan_mode": "Full Scan"
    }
  }'
```

#### Force re-classification (override cache)

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "urls": ["https://example.com/ad.mp4"],
    "settings": {
      "override": true
    }
  }'
```

#### Disable web search and vision

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "urls": ["https://example.com/ad.mp4"],
    "settings": {
      "enable_search": false,
      "enable_vision": false
    }
  }'
```

#### OpenAI provider with specific model

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "urls": ["https://example.com/ad.mp4"],
    "settings": {
      "provider": "OpenAI",
      "model_name": "gpt-4o",
      "enable_search": true,
      "enable_vision": true
    }
  }'
```

#### Anthropic provider with specific model

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "urls": ["https://example.com/ad.mp4"],
    "settings": {
      "provider": "Anthropic",
      "model_name": "claude-3-5-sonnet-20241022",
      "context_size": 32768
    }
  }'
```

#### Large batch with high parallelism

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "urls": [
      "https://cdn.example.com/ad001.mp4",
      "https://cdn.example.com/ad002.mp4",
      "https://cdn.example.com/ad003.mp4",
      "https://cdn.example.com/ad004.mp4",
      "https://cdn.example.com/ad005.mp4"
    ],
    "settings": {
      "workers": 8,
      "scan_mode": "Tail Only",
      "ocr_mode": "🚀 Fast"
    }
  }'
```

---

### 2. Submit Folder (Server-side Path)

**Endpoint:** `POST /jobs/by-folder`

Scans a folder on the server's filesystem for `.mp4` and `.mov` files and creates a job for each.

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-folder \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "folder_path": "/path/to/local/videos",
    "settings": {
      "categories": "Automotive, Insurance",
      "scan_mode": "Tail Only"
    }
  }'
```

#### Agent mode for a folder

```bash
curl -X POST http://127.0.0.1:8000/jobs/by-folder \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "agent",
    "folder_path": "/data/video_ads",
    "settings": {
      "enable_search": true,
      "enable_vision": true,
      "context_size": 16384
    }
  }'
```

---

### 3. Upload a File Directly

**Endpoint:** `POST /jobs/upload`

Upload a video file from your local machine. Uses multipart/form-data. Settings are passed as individual form fields.

#### Minimal upload

```bash
curl -X POST http://127.0.0.1:8000/jobs/upload \
  -F "file=@/path/to/video.mp4" \
  -F "mode=pipeline"
```

#### Upload with full settings

```bash
curl -X POST http://127.0.0.1:8000/jobs/upload \
  -F "file=@/path/to/video.mp4" \
  -F "mode=pipeline" \
  -F "categories=Cars, Finance" \
  -F "provider=Gemini CLI" \
  -F "model_name=Gemini CLI Default" \
  -F "ocr_engine=EasyOCR" \
  -F 'ocr_mode=🚀 Fast' \
  -F "scan_mode=Tail Only" \
  -F "override=false" \
  -F "enable_search=true" \
  -F "enable_vision=true" \
  -F "context_size=8192" \
  -F "workers=2"
```

#### Upload in agent mode

```bash
curl -X POST http://127.0.0.1:8000/jobs/upload \
  -F "file=@/path/to/video.mp4" \
  -F "mode=agent" \
  -F "enable_search=true" \
  -F "enable_vision=true" \
  -F "context_size=16384"
```

#### Upload with Tesseract, full scan, override

```bash
curl -X POST http://127.0.0.1:8000/jobs/upload \
  -F "file=@/path/to/ocr_heavy.mp4" \
  -F "mode=pipeline" \
  -F "ocr_engine=Tesseract" \
  -F 'ocr_mode=🔍 Thorough' \
  -F "scan_mode=Full Scan" \
  -F "override=true"
```

---

## Job Status & Results

All job-specific routes automatically proxy to the correct node based on the job ID prefix (e.g., `node-a-<uuid>` → port 8000).

```bash
# Get recent jobs (last 50) on this node
curl http://127.0.0.1:8000/jobs

# Get a specific job's status
JOB_ID="node-a-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
curl http://127.0.0.1:8000/jobs/$JOB_ID

# Get the final classification result
curl http://127.0.0.1:8000/jobs/$JOB_ID/result

# Get extracted frame artifacts (vision frames gallery)
curl http://127.0.0.1:8000/jobs/$JOB_ID/artifacts

# Get agent mode incremental event log
curl http://127.0.0.1:8000/jobs/$JOB_ID/events

# Delete a job
curl -X DELETE http://127.0.0.1:8000/jobs/$JOB_ID

# All jobs across entire cluster (aggregated fan-out)
curl http://127.0.0.1:8000/cluster/jobs

# Per-node admin job list (internal use)
curl "http://127.0.0.1:8000/admin/jobs"
curl "http://127.0.0.1:8001/admin/jobs"
```

---

## Poll Until Complete (Shell Script Pattern)

```bash
#!/usr/bin/env bash
JOB_ID="node-a-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
BASE_URL="http://127.0.0.1:8000"

while true; do
  STATUS=$(curl -s "$BASE_URL/jobs/$JOB_ID" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "Status: $STATUS"
  if [[ "$STATUS" == "completed" || "$STATUS" == "failed" ]]; then
    break
  fi
  sleep 3
done

# Fetch the result
curl -s "$BASE_URL/jobs/$JOB_ID/result" | python3 -m json.tool
```

---

## Full End-to-End Example

```bash
# 1. Submit a job
RESPONSE=$(curl -s -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "urls": ["https://example.com/car_ad.mp4"],
    "settings": {
      "categories": "Automotive, Insurance",
      "provider": "Gemini CLI",
      "scan_mode": "Tail Only",
      "ocr_mode": "🚀 Fast",
      "enable_search": true,
      "enable_vision": true
    }
  }')

echo "$RESPONSE"
# Example: [{"job_id": "node-a-abc-...", "status": "queued"}]

JOB_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['job_id'])")

# 2. Poll for completion
while true; do
  STATUS=$(curl -s "http://127.0.0.1:8000/jobs/$JOB_ID" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  PROGRESS=$(curl -s "http://127.0.0.1:8000/jobs/$JOB_ID" | python3 -c "import sys,json; print(json.load(sys.stdin)['progress'])")
  echo "$(date): $STATUS ($PROGRESS)"
  [[ "$STATUS" == "completed" || "$STATUS" == "failed" ]] && break
  sleep 3
done

# 3. Get the result
curl -s "http://127.0.0.1:8000/jobs/$JOB_ID/result" | python3 -m json.tool

# 4. Get artifacts (extracted frames)
curl -s "http://127.0.0.1:8000/jobs/$JOB_ID/artifacts" | python3 -m json.tool
```

---

## Parameter Quick-Reference Matrix

| Use Case              | `mode`     | `scan_mode` | `ocr_engine` | `ocr_mode`    | `enable_vision` | `enable_search`           |
| --------------------- | ---------- | ----------- | ------------ | ------------- | --------------- | ------------------------- |
| Fast batch            | `pipeline` | `Tail Only` | `EasyOCR`    | `🚀 Fast`     | `true`          | `true`                    |
| Thorough single       | `agent`    | `Full Scan` | `Tesseract`  | `🔍 Thorough` | `true`          | `true`                    |
| OCR-heavy ads         | `pipeline` | `Full Scan` | `Tesseract`  | `🔍 Thorough` | `false`         | `false`                   |
| Text-only (no vision) | `pipeline` | `Tail Only` | `EasyOCR`    | `🚀 Fast`     | `false`         | `false`                   |
| Debug / re-run        | `pipeline` | `Full Scan` | `EasyOCR`    | `🔍 Thorough` | `true`          | `true` + `override: true` |
| Agentic reasoning     | `agent`    | `Tail Only` | `EasyOCR`    | `🚀 Fast`     | `true`          | `true`                    |
