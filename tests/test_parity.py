"""
tests/test_parity.py
====================
Parity tests: ensure the FastAPI service produces outputs that match
the golden reference output captured from the service core modules
(which are the extracted / ported version of poc/combined.py).

Test IDs map 1:1 with fixture IDs in tests/fixtures/parity_fixtures.json.

Run all:
    pytest tests/test_parity.py -v

Run a single fixture:
    pytest tests/test_parity.py -k short_url -v

Refresh goldens then re-run:
    python scripts/capture_goldens.py --force
    pytest tests/test_parity.py -v
"""

import json
import re
import time

import pytest
import requests

from tests.conftest import (
    CONFIDENCE_TOLERANCE,
    API_BASE,
    load_fixtures,
    load_golden,
    submit_job,
    poll_until_done,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_job_result(job_id: str) -> dict | None:
    """
    Fetch /jobs/{job_id}/result and return a normalized dict with keys:
        brand, category, category_id, confidence, reasoning

    The worker stores result_json as DataFrame.to_dict(orient='records'), which
    is a list of row dicts with verbose column names like 'URL / Path', 'Brand', etc.
    We extract the first row and normalise to the golden's key schema.
    """
    resp = requests.get(f"{API_BASE}/jobs/{job_id}/result")
    assert resp.status_code == 200, f"Result fetch failed: {resp.status_code}"
    payload = resp.json()
    raw = payload.get("result")
    if raw is None:
        return None

    # Handle list-of-rows (DataFrame.to_dict(orient="records")) or bare dict
    row = raw[0] if isinstance(raw, list) else raw
    if not row:
        return None

    return {
        "brand":       row.get("Brand")       or row.get("brand",       "Unknown"),
        "category":    row.get("Category")    or row.get("category",    "Unknown"),
        "category_id": row.get("Category ID") or row.get("category_id", ""),
        "confidence":  float(row.get("Confidence") or row.get("confidence") or 0.0),
        "reasoning":   row.get("Reasoning")   or row.get("reasoning",   ""),
    }


def normalise(s: str) -> str:
    """Case-fold and strip for string comparisons."""
    return (s or "").strip().lower()


# ── Parametrize over all fixtures ───────────────────────────────────────────

ALL_FIXTURES = load_fixtures()


@pytest.fixture(params=[f["id"] for f in ALL_FIXTURES], scope="module")
def fixture_data(request):
    return next(f for f in ALL_FIXTURES if f["id"] == request.param)


# ── Core parity test class ───────────────────────────────────────────────────

class TestAPIParity:
    """
    For each fixture:
      1. Load the golden reference.
      2. Submit the same input to the API.
      3. Wait for completion.
      4. Compare result fields.

    Tolerances
    ----------
    - brand (str):      EXACT match (case-insensitive). No tolerance.
    - category (str):   EXACT match (case-insensitive). No tolerance.
    - category_id (str): EXACT match. No tolerance.
    - confidence (float): ± CONFIDENCE_TOLERANCE (0.25 by default).
                          Justified: LLM temperature/sampling introduces minor float drift.
    - reasoning (str):  NOT compared. LLM prose varies across runs.
    - frame_count (int): EXACT match. Frame extraction is deterministic for a given video + scan strategy.
    - ocr_has_text (bool): golden says whether OCR found text; API must agree.
    """

    def test_service_healthy(self, api_available):
        """Sanity: API health endpoint responds OK before any heavy tests."""
        r = requests.get(f"{API_BASE}/health")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_brand_matches_golden(self, fixture_data, api_available):
        golden = load_golden(fixture_data["id"])
        job_id = submit_job(fixture_data)
        job    = poll_until_done(job_id)

        assert job["status"] == "completed", (
            f"Job {job_id} failed: {job.get('error')}"
        )

        result = get_job_result(job_id)
        assert result is not None, f"Job {job_id} has no result_json"

        golden_brand = normalise(golden["result"]["brand"])
        api_brand    = normalise(result.get("brand", ""))

        assert api_brand == golden_brand, (
            f"[{fixture_data['id']}] Brand mismatch: API='{api_brand}' != Golden='{golden_brand}'"
        )

    def test_category_matches_golden(self, fixture_data, api_available):
        golden = load_golden(fixture_data["id"])
        job_id = submit_job(fixture_data)
        job    = poll_until_done(job_id)

        assert job["status"] == "completed"

        result = get_job_result(job_id)
        assert result is not None

        golden_cat = normalise(golden["result"]["category"])
        api_cat    = normalise(result.get("category", ""))

        assert api_cat == golden_cat, (
            f"[{fixture_data['id']}] Category mismatch: API='{api_cat}' != Golden='{golden_cat}'"
        )

    def test_category_id_matches_golden(self, fixture_data, api_available):
        golden = load_golden(fixture_data["id"])
        job_id = submit_job(fixture_data)
        job    = poll_until_done(job_id)

        assert job["status"] == "completed"

        result = get_job_result(job_id)
        assert result is not None

        golden_id = normalise(golden["result"]["category_id"])
        api_id    = normalise(result.get("category_id", ""))

        assert api_id == golden_id, (
            f"[{fixture_data['id']}] Category ID mismatch: API='{api_id}' != Golden='{golden_id}'"
        )

    def test_confidence_within_tolerance(self, fixture_data, api_available):
        """
        Confidence is a float reported by the LLM. We allow ± CONFIDENCE_TOLERANCE
        (default 0.25) because temperature/sampling can shift the exact value between
        runs. This tolerance is intentional and justified.
        """
        golden = load_golden(fixture_data["id"])
        job_id = submit_job(fixture_data)
        job    = poll_until_done(job_id)

        assert job["status"] == "completed"

        result = get_job_result(job_id)
        assert result is not None

        golden_conf = float(golden["result"].get("confidence", 0.0))
        api_conf    = float(result.get("confidence", 0.0))

        assert abs(api_conf - golden_conf) <= CONFIDENCE_TOLERANCE, (
            f"[{fixture_data['id']}] Confidence delta {abs(api_conf - golden_conf):.3f} "
            f"exceeds tolerance {CONFIDENCE_TOLERANCE} "
            f"(API={api_conf:.4f}, Golden={golden_conf:.4f})"
        )

    def test_result_fields_present(self, fixture_data, api_available):
        """Result record must contain all required fields."""
        golden = load_golden(fixture_data["id"])
        job_id = submit_job(fixture_data)
        job    = poll_until_done(job_id)

        assert job["status"] == "completed"

        result = get_job_result(job_id)
        assert result is not None

        required_fields = {"brand", "category", "confidence", "reasoning"}
        missing = required_fields - set(result.keys())
        assert not missing, (
            f"[{fixture_data['id']}] Result missing fields: {missing}"
        )


# ── OCR Presence Test ────────────────────────────────────────────────────────

class TestOCRParity:
    """
    Verify OCR behavior: if the golden captured text from a video,
    the API result must also have produced non-empty reasoning
    (proxy for OCR having worked — the OCR text feeds into the LLM prompt).

    We do NOT compare exact OCR strings because OCR is non-deterministic
    at the character level (layout changes can reorder words slightly).
    We DO check: if golden says text was found → API result must be non-empty.
    """

    def test_ocr_presence_consistent(self, fixture_data, api_available):
        golden = load_golden(fixture_data["id"])
        golden_has_text = golden.get("ocr_has_text", True)

        if not golden_has_text:
            pytest.skip(f"Golden for '{fixture_data['id']}' reports no OCR text — skipping presence check")

        job_id = submit_job(fixture_data)
        job    = poll_until_done(job_id)

        assert job["status"] == "completed"

        result = get_job_result(job_id)
        assert result is not None

        # Reasoning will be populated only if OCR → LLM succeeded
        reasoning = result.get("reasoning", "")
        assert reasoning, (
            f"[{fixture_data['id']}] Golden has OCR text, but API result has empty reasoning "
            f"(suggests OCR/LLM pipeline failure)"
        )


# ── Scan Strategy Test ───────────────────────────────────────────────────────

class TestScanStrategyParity:
    """
    For the fixture flagged with scan_strategy_check, verify that Tail Only
    produces fewer frames than Full Scan.  This is a structural behavior test,
    independent of the LLM output.

    We run this entirely against the service core modules (not the API) to
    avoid a 2× LLM cost in CI.
    """

    def _count_frames(self, url: str) -> tuple[int, int]:
        """Returns (tail_only_count, full_scan_count)."""
        from video_service.core.video_io import (
            extract_frames_for_pipeline,
            extract_frames_for_agent,
            get_stream_url,
        )
        frames_tail, cap = extract_frames_for_pipeline(url)
        if cap and cap.isOpened():
            cap.release()

        frames_full, cap = extract_frames_for_agent(url)
        if cap and cap.isOpened():
            cap.release()

        return len(frames_tail), len(frames_full)

    def test_tail_only_fewer_frames_than_full_scan(self):
        fixtures = load_fixtures()
        scan_fixture = next(
            (f for f in fixtures if f.get("scan_strategy_check", {}).get("tail_only_frame_count_lt_full")),
            None,
        )
        if scan_fixture is None:
            pytest.skip("No fixture flagged with scan_strategy_check")

        target_url = scan_fixture.get("url") or scan_fixture.get("local_path")
        tail_count, full_count = self._count_frames(target_url)

        assert tail_count > 0, "Tail Only extracted 0 frames"
        assert full_count > 0, "Full Scan extracted 0 frames"
        assert tail_count < full_count, (
            f"Expected Tail Only ({tail_count}) < Full Scan ({full_count}) for scan strategy fixture. "
            f"If the video is very short both strategies converge — use a longer fixture."
        )


# ── Frame Count Regression Test ──────────────────────────────────────────────

class TestFrameCount:
    """
    Frame extraction must be deterministic: same video + same scan mode
    must always produce the same count as the golden.

    We test this at the module level (no LLM cost) for fast CI feedback.
    """

    def test_frame_count_matches_golden(self, fixture_data):
        golden = load_golden(fixture_data["id"])
        golden_count = golden.get("frame_count")

        if golden_count is None:
            pytest.skip(f"Golden '{fixture_data['id']}' has no frame_count field")

        from video_service.core.video_io import extract_frames_for_pipeline
        target = fixture_data.get("url") or fixture_data.get("local_path")
        frames, cap = extract_frames_for_pipeline(target)
        if cap and cap.isOpened():
            cap.release()

        assert len(frames) == golden_count, (
            f"[{fixture_data['id']}] Frame count changed: got {len(frames)}, expected {golden_count}. "
            f"This indicates a change in the extraction logic."
        )
