"""
tests/conftest.py
-----------------
Shared fixtures for the parity test suite.
"""
import json
import os
import time
from pathlib import Path

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_FILE = PROJECT_ROOT / "tests" / "fixtures" / "parity_fixtures.json"
GOLDEN_DIR = PROJECT_ROOT / "tests" / "golden"

API_BASE = os.environ.get("PARITY_API_URL", "http://127.0.0.1:8000")
JOB_POLL_INTERVAL = float(os.environ.get("PARITY_POLL_INTERVAL", "3"))
JOB_TIMEOUT_SECONDS = float(os.environ.get("PARITY_JOB_TIMEOUT", "300"))

# ── Tolerance configuration ──────────────────────────────────────────────────
# Confidence is a float emitted by the LLM; minor variation is expected across
# identical runs due to temperature/token sampling.  We allow ±0.25 tolerance.
CONFIDENCE_TOLERANCE = float(os.environ.get("PARITY_CONFIDENCE_TOLERANCE", "0.25"))

# Brand / category are strings: we expect EXACT matches (case-insensitive).
# Reasoning freetext is NOT compared — it's LLM prose.
# ────────────────────────────────────────────────────────────────────────────


def load_fixtures() -> list[dict]:
    return json.loads(FIXTURES_FILE.read_text())["fixtures"]


def load_golden(fixture_id: str) -> dict:
    p = GOLDEN_DIR / f"{fixture_id}.json"
    if not p.exists():
        pytest.skip(
            f"Golden not found for '{fixture_id}'. "
            f"Run: python scripts/capture_goldens.py --fixture {fixture_id}"
        )
    return json.loads(p.read_text())


def submit_job(fixture: dict) -> str:
    """POST the fixture to the API and return job_id."""
    s = fixture["settings"]
    target = fixture.get("url") or fixture.get("local_path")

    if fixture["source_type"] == "local":
        local_path = PROJECT_ROOT / (fixture["local_path"] or "")
        if not local_path.exists():
            pytest.skip(f"Local fixture file missing: {local_path}")
        with open(local_path, "rb") as fh:
            resp = requests.post(
                # ?internal=1 bypasses cluster round-robin: multipart bodies
                # cannot be re-streamed through the proxy to another node.
                f"{API_BASE}/jobs/upload?internal=1",
                files={"file": (local_path.name, fh, "video/mp4")},
                data={
                    "mode": "pipeline",
                    "categories": s["categories"],
                    "provider": s["provider"],
                    "model_name": s["model_name"],
                    "ocr_engine": s["ocr_engine"],
                    "ocr_mode":   s["ocr_mode"],
                    "scan_mode":  s["scan_mode"],
                    # FastAPI bool Form coercion: truthy = '1', falsy = '0'
                    "override":      "1" if s["override"] else "0",
                    "enable_search": "1" if s["enable_search"] else "0",
                    "enable_vision": "1" if s["enable_vision"] else "0",
                    "context_size": str(s["context_size"]),
                },
            )
        resp.raise_for_status()
        return resp.json()["job_id"]
    else:
        resp = requests.post(
            f"{API_BASE}/jobs/by-urls",
            json={
                "mode": "pipeline",
                "urls": [target],
                "settings": s,
            },
        )
        resp.raise_for_status()
        return resp.json()[0]["job_id"]


def poll_until_done(job_id: str) -> dict:
    """Poll /jobs/{job_id} until status is completed or failed."""
    deadline = time.time() + JOB_TIMEOUT_SECONDS
    while time.time() < deadline:
        resp = requests.get(f"{API_BASE}/jobs/{job_id}")
        assert resp.status_code == 200, f"Job poll failed: {resp.status_code} {resp.text}"
        job = resp.json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(JOB_POLL_INTERVAL)
    pytest.fail(f"Job {job_id} did not complete within {JOB_TIMEOUT_SECONDS}s")


@pytest.fixture(scope="session")
def api_available():
    """Skip entire session if the API is not reachable."""
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        assert r.status_code == 200
    except Exception as e:
        pytest.skip(f"API not reachable at {API_BASE}: {e}")


@pytest.fixture(scope="session")
def all_fixtures():
    return load_fixtures()
