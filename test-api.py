import pytest
from fastapi.testclient import TestClient
from video_service.app.main import app
from video_service.db.database import init_db

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200

def test_submit_url():
    response = client.post("/jobs/by-urls", json={
        "mode": "pipeline",
        "urls": ["http://example.com"],
        "settings": {}
    })
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert "job_id" in data[0]

def test_submit_folder():
    response = client.post("/jobs/by-folder", json={
        "mode": "pipeline",
        "folder_path": "/tmp",
        "settings": {}
    })
    assert response.status_code == 200

def test_upload():
    response = client.post(
        "/jobs/upload",
        data={"mode": "pipeline", "settings_json": "{}"},
        files={"file": ("test.mp4", b"dummy content", "video/mp4")}
    )
    assert response.status_code == 200
    assert "job_id" in response.json()

def test_get_jobs():
    response = client.get("/jobs")
    assert response.status_code == 200

def test_admin_jobs():
    response = client.get("/admin/jobs")
    assert response.status_code == 200
