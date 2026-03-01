import sqlite3

import pytest

from video_service.app import main
from video_service.app.models.job import BenchmarkSuiteUpdateRequest, BenchmarkTestUpdateRequest

pytestmark = pytest.mark.unit


def _create_schema(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE benchmark_truth (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                suite_id TEXT DEFAULT '',
                video_url TEXT NOT NULL,
                expected_ocr_text TEXT DEFAULT '',
                expected_categories_json TEXT DEFAULT '[]',
                expected_brand TEXT DEFAULT '',
                expected_category TEXT DEFAULT '',
                expected_confidence REAL,
                expected_reasoning TEXT DEFAULT '',
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE benchmark_suites (
                id TEXT PRIMARY KEY,
                truth_id TEXT NOT NULL,
                name TEXT DEFAULT '',
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                matrix_json TEXT DEFAULT '{}',
                created_by TEXT DEFAULT 'api',
                total_jobs INTEGER DEFAULT 0,
                completed_jobs INTEGER DEFAULT 0,
                failed_jobs INTEGER DEFAULT 0,
                evaluated_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE benchmark_result (
                id TEXT PRIMARY KEY,
                suite_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                duration_seconds REAL,
                classification_accuracy REAL,
                ocr_accuracy REAL,
                composite_accuracy REAL,
                params_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                benchmark_suite_id TEXT,
                benchmark_truth_id TEXT,
                status TEXT DEFAULT 'queued'
            )
            """
        )

        conn.execute(
            """
            INSERT INTO benchmark_truth (
                id, name, suite_id, video_url, expected_ocr_text, expected_categories_json,
                expected_brand, expected_category, expected_confidence, expected_reasoning, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "test-1",
                "Test One",
                "suite-1",
                "https://video.example/ad.mp4",
                "ocr text",
                '["Retail"]',
                "The Brick",
                "Retail",
                0.9,
                "because",
                '{}',
            ),
        )
        conn.execute(
            """
            INSERT INTO benchmark_suites (
                id, truth_id, name, description, status, matrix_json, total_jobs, completed_jobs, failed_jobs
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "suite-1",
                "test-1",
                "Initial Suite",
                "Initial Description",
                "running",
                '{}',
                3,
                1,
                0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _db_factory(path: str):
    def _open_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return _open_db


def test_benchmark_suite_and_test_management_endpoints(monkeypatch, tmp_path):
    db_path = str(tmp_path / "benchmark_mgmt.db")
    _create_schema(db_path)
    monkeypatch.setattr(main, "get_db", _db_factory(db_path))

    suite = main.get_benchmark_suite("suite-1")
    assert suite["suite_id"] == "suite-1"
    assert len(suite["tests"]) == 1
    assert suite["tests"][0]["test_id"] == "test-1"

    updated_suite = main.update_benchmark_suite(
        "suite-1",
        BenchmarkSuiteUpdateRequest(name="Renamed Suite", description="Updated Description"),
    )
    assert updated_suite["name"] == "Renamed Suite"
    assert updated_suite["description"] == "Updated Description"

    updated_test = main.update_benchmark_test(
        "test-1",
        BenchmarkTestUpdateRequest(
            source_url="https://video.example/new.mp4",
            expected_category="Retail - Home Improvement & Building Supplies",
            expected_brand="The Brick",
            expected_confidence=0.95,
            expected_reasoning="Matched by slogan and site",
            expected_ocr_text="new ocr",
        ),
    )
    assert updated_test["source_url"] == "https://video.example/new.mp4"
    assert updated_test["expected_category"] == "Retail - Home Improvement & Building Supplies"
    assert updated_test["expected_confidence"] == 0.95

    deleted_test = main.delete_benchmark_test("test-1")
    assert deleted_test["status"] == "deleted"
    assert deleted_test["test_id"] == "test-1"

    # Reinsert a test so suite deletion can cascade it.
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO benchmark_truth (
                id, name, suite_id, video_url, expected_ocr_text, expected_categories_json,
                expected_brand, expected_category, expected_confidence, expected_reasoning, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "test-2",
                "Test Two",
                "suite-1",
                "https://video.example/ad2.mp4",
                "",
                '[]',
                "",
                "",
                None,
                "",
                '{}',
            ),
        )
        conn.execute("UPDATE benchmark_suites SET truth_id = ? WHERE id = ?", ("test-2", "suite-1"))
        conn.commit()
    finally:
        conn.close()

    deleted_suite = main.delete_benchmark_suite("suite-1")
    assert deleted_suite["status"] == "deleted"
    assert deleted_suite["suite_id"] == "suite-1"

    conn = sqlite3.connect(db_path)
    try:
        suites_count = conn.execute("SELECT COUNT(*) FROM benchmark_suites").fetchone()[0]
        tests_count = conn.execute("SELECT COUNT(*) FROM benchmark_truth").fetchone()[0]
    finally:
        conn.close()

    assert suites_count == 0
    assert tests_count == 0
