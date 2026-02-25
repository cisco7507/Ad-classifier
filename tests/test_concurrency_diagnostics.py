import pytest

from video_service.app import main
from video_service.core import concurrency

pytestmark = pytest.mark.unit


def test_concurrency_diagnostics_reads_env(monkeypatch):
    monkeypatch.setenv("WORKER_PROCESSES", "4")
    monkeypatch.setenv("PIPELINE_THREADS_PER_JOB", "2")

    payload = concurrency.get_concurrency_diagnostics()
    assert payload["worker_processes_configured"] == 4
    assert payload["pipeline_threads_per_job"] == 2
    assert "up to 4 concurrent job(s)" in payload["effective_mode"]


def test_concurrency_diagnostics_endpoint(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_concurrency_diagnostics",
        lambda: {
            "worker_processes_configured": 2,
            "pipeline_threads_per_job": 1,
            "effective_mode": "ok",
        },
    )
    payload = main.concurrency_diagnostics()
    assert payload["worker_processes_configured"] == 2
    assert payload["pipeline_threads_per_job"] == 1
