import asyncio

import pytest

from video_service.app import main

pytestmark = pytest.mark.unit


class _DummyResponse:
    def __init__(self, status_code: int, payload: list[dict]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> list[dict]:
        return self._payload


class _DummyAsyncClient:
    def __init__(self, payloads_by_url: dict[str, list[dict]]):
        self.payloads_by_url = payloads_by_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, timeout: float):
        payload = self.payloads_by_url.get(url, [])
        return _DummyResponse(200, payload)


def test_cluster_jobs_dedupes_by_job_id_and_keeps_newest_updated_at(monkeypatch):
    monkeypatch.setattr(main.cluster, "enabled", True, raising=False)
    monkeypatch.setattr(
        main.cluster,
        "nodes",
        {"node-a": "http://node-a", "node-b": "http://node-b"},
        raising=False,
    )
    monkeypatch.setattr(
        main.cluster,
        "node_status",
        {"node-a": True, "node-b": True},
        raising=False,
    )
    monkeypatch.setattr(main.cluster, "internal_timeout", 1.0, raising=False)

    payloads = {
        "http://node-a/admin/jobs?internal=1": [
            {
                "job_id": "node-a-uuid-1",
                "created_at": "2026-02-24 11:00:00",
                "updated_at": "2026-02-24 11:01:00",
                "status": "processing",
            },
            {
                "job_id": "node-a-uuid-2",
                "created_at": "2026-02-24 11:02:00",
                "updated_at": "2026-02-24 11:03:00",
                "status": "queued",
            },
        ],
        "http://node-b/admin/jobs?internal=1": [
            {
                "job_id": "node-a-uuid-1",
                "created_at": "2026-02-24 11:00:00",
                "updated_at": "2026-02-24 11:05:00",
                "status": "completed",
            }
        ],
    }
    monkeypatch.setattr(
        main.httpx,
        "AsyncClient",
        lambda: _DummyAsyncClient(payloads),
    )

    jobs = asyncio.run(main.cluster_jobs())

    assert len(jobs) == 2
    assert [job["job_id"] for job in jobs] == ["node-a-uuid-2", "node-a-uuid-1"]
    deduped = next(job for job in jobs if job["job_id"] == "node-a-uuid-1")
    assert deduped["updated_at"] == "2026-02-24 11:05:00"
    assert deduped["status"] == "completed"
