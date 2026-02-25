from pathlib import Path

import pytest

from video_service.db import database

pytestmark = pytest.mark.unit


def test_db_path_is_absolute():
    assert Path(database.DB_PATH).is_absolute()


def test_get_db_creates_parent_directory(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "svc.db"
    monkeypatch.setattr(database, "DB_PATH", str(target))

    conn = database.get_db()
    try:
        row = conn.execute("SELECT 1 AS v").fetchone()
        assert row["v"] == 1
    finally:
        conn.close()

    assert target.parent.exists()

