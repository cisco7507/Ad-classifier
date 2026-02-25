import asyncio

import pytest

from video_service.app import main
from video_service.app.models.job import FilePathRequest, JobMode, JobSettings

pytestmark = pytest.mark.unit


class _Req:
    query_params = {"internal": "1"}


def test_create_job_filepath_accepts_windows_and_unc_paths_without_mangling(monkeypatch):
    captured = {}

    def _fake_create_job(mode: str, settings: JobSettings, url: str = None) -> str:
        captured["mode"] = mode
        captured["url"] = url
        return "node-a-job-123"

    monkeypatch.setattr(main, "_create_job", _fake_create_job)

    request = FilePathRequest(
        mode=JobMode.pipeline,
        file_path=r"\\server\share\ads\spot.mp4",
        settings=JobSettings(),
    )

    response = asyncio.run(main.create_job_filepath(_Req(), request))

    assert response.job_id == "node-a-job-123"
    assert captured["mode"] == "pipeline"
    assert captured["url"] == r"\\server\share\ads\spot.mp4"
