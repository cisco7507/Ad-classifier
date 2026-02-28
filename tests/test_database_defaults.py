import importlib
import os

import pytest

import video_service.db.database as database

pytestmark = pytest.mark.unit


def test_default_database_path_uses_node_name_when_database_path_not_set(monkeypatch):
    original_database_path = os.environ.get("DATABASE_PATH")
    original_node_name = os.environ.get("NODE_NAME")

    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.setenv("NODE_NAME", "node-b")
    try:
        importlib.reload(database)
        assert database.DB_PATH.endswith("video_service_node-b.db")
    finally:
        if original_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = original_database_path

        if original_node_name is None:
            os.environ.pop("NODE_NAME", None)
        else:
            os.environ["NODE_NAME"] = original_node_name
        importlib.reload(database)
