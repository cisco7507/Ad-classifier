import pytest
import pandas as pd

from video_service.workers import worker

pytestmark = pytest.mark.unit


def test_get_worker_process_count_defaults_to_one(monkeypatch):
    monkeypatch.delenv("WORKER_PROCESSES", raising=False)
    assert worker._get_worker_process_count() == 1


def test_get_worker_process_count_invalid_or_non_positive(monkeypatch):
    monkeypatch.setenv("WORKER_PROCESSES", "abc")
    assert worker._get_worker_process_count() == 1

    monkeypatch.setenv("WORKER_PROCESSES", "0")
    assert worker._get_worker_process_count() == 1

    monkeypatch.setenv("WORKER_PROCESSES", "-7")
    assert worker._get_worker_process_count() == 1


def test_get_worker_process_count_positive_integer(monkeypatch):
    monkeypatch.setenv("WORKER_PROCESSES", "4")
    assert worker._get_worker_process_count() == 4


def test_run_worker_uses_single_process_path(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(worker, "_get_worker_process_count", lambda: 1)
    monkeypatch.setattr(worker, "_run_single_worker", lambda: calls.append("single"))
    monkeypatch.setattr(worker, "_run_worker_supervisor", lambda count: calls.append(f"supervisor:{count}"))

    worker.run_worker()
    assert calls == ["single"]


def test_run_worker_uses_supervisor_path(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(worker, "_get_worker_process_count", lambda: 3)
    monkeypatch.setattr(worker, "_run_single_worker", lambda: calls.append("single"))
    monkeypatch.setattr(worker, "_run_worker_supervisor", lambda count: calls.append(f"supervisor:{count}"))

    worker.run_worker()
    assert calls == ["supervisor:3"]


def test_run_pipeline_uses_pipeline_threads_per_job_env(monkeypatch):
    captured = {}
    monkeypatch.setenv("PIPELINE_THREADS_PER_JOB", "3")
    monkeypatch.setattr(worker, "_stage_callback", lambda _job_id: (lambda _s, _d: None))

    def _fake_run_pipeline_job(**kwargs):
        captured["workers"] = kwargs["workers"]
        yield ({}, "", "", [], pd.DataFrame([{"Brand": "BrandX"}]))

    monkeypatch.setattr(worker, "run_pipeline_job", _fake_run_pipeline_job)

    worker._run_pipeline("job-1", "https://example.test/ad.mp4", {})
    assert captured["workers"] == 3


def test_extract_agent_ocr_text_supports_observation_without_scene_prefix():
    events = [
        "2026-02-28T00:00:00Z agent:\n--- Step 1 ---\nAction: [TOOL: OCR]\nResult: Observation: VOLVO | XC90",
    ]
    assert worker._extract_agent_ocr_text(events) == "VOLVO | XC90"
