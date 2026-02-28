import sqlite3
import os
from pathlib import Path
from contextlib import closing


def _default_database_path() -> str:
    node_name = (os.environ.get("NODE_NAME") or "node-a").strip() or "node-a"
    return f"video_service_{node_name}.db"


def _resolve_database_path(raw_path: str) -> str:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return str(path)
    # Keep relative DB paths deterministic regardless of launch cwd.
    repo_root = Path(__file__).resolve().parents[2]
    return str((repo_root / path).resolve())


DB_PATH = _resolve_database_path(os.environ.get("DATABASE_PATH") or _default_database_path())
SQLITE_TIMEOUT_SECONDS = float(os.environ.get("SQLITE_TIMEOUT_SECONDS", "30"))
SQLITE_BUSY_TIMEOUT_MS = int(os.environ.get("SQLITE_BUSY_TIMEOUT_MS", "30000"))

def get_db():
    db_parent = os.path.dirname(DB_PATH)
    if db_parent:
        os.makedirs(db_parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    # busy_timeout is per-connection; set it for every connection.
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS};")
    return conn

def init_db():
    with closing(get_db()) as conn:
        with conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    stage TEXT,
                    stage_detail TEXT,
                    brand TEXT,
                    category TEXT,
                    category_id TEXT,
                    benchmark_suite_id TEXT,
                    benchmark_truth_id TEXT,
                    benchmark_params_json TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    progress REAL DEFAULT 0,
                    error TEXT,
                    settings TEXT,
                    mode TEXT,
                    url TEXT,
                    result_json TEXT,
                    artifacts_json TEXT,
                    events TEXT DEFAULT '[]'
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_stats (
                    id TEXT PRIMARY KEY,
                    completed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                    status TEXT NOT NULL,
                    mode TEXT,
                    brand TEXT,
                    category TEXT,
                    category_id TEXT,
                    duration_seconds REAL,
                    scan_mode TEXT,
                    provider TEXT,
                    model_name TEXT,
                    ocr_engine TEXT,
                    source_type TEXT
                )
            """)

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmark_truth (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    video_url TEXT NOT NULL,
                    expected_ocr_text TEXT DEFAULT '',
                    expected_categories_json TEXT DEFAULT '[]',
                    metadata_json TEXT DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmark_suites (
                    id TEXT PRIMARY KEY,
                    truth_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    matrix_json TEXT DEFAULT '{}',
                    created_by TEXT DEFAULT 'api',
                    total_jobs INTEGER DEFAULT 0,
                    completed_jobs INTEGER DEFAULT 0,
                    failed_jobs INTEGER DEFAULT 0,
                    evaluated_at TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmark_result (
                    id TEXT PRIMARY KEY,
                    suite_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    duration_seconds REAL,
                    classification_accuracy REAL,
                    ocr_accuracy REAL,
                    composite_accuracy REAL,
                    params_json TEXT DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            existing_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "stage" not in existing_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN stage TEXT")
            if "stage_detail" not in existing_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN stage_detail TEXT")
            if "brand" not in existing_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN brand TEXT")
            if "category" not in existing_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN category TEXT")
            if "category_id" not in existing_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN category_id TEXT")
            if "duration_seconds" not in existing_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN duration_seconds REAL")
            if "benchmark_suite_id" not in existing_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN benchmark_suite_id TEXT")
            if "benchmark_truth_id" not in existing_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN benchmark_truth_id TEXT")
            if "benchmark_params_json" not in existing_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN benchmark_params_json TEXT")

            conn.execute("UPDATE jobs SET stage = COALESCE(stage, status, 'queued') WHERE stage IS NULL")
            conn.execute("UPDATE jobs SET stage_detail = COALESCE(stage_detail, '') WHERE stage_detail IS NULL")
            conn.execute("UPDATE jobs SET brand = COALESCE(brand, '') WHERE brand IS NULL")
            conn.execute("UPDATE jobs SET category = COALESCE(category, '') WHERE category IS NULL")
            conn.execute("UPDATE jobs SET category_id = COALESCE(category_id, '') WHERE category_id IS NULL")
            conn.execute("UPDATE jobs SET benchmark_suite_id = COALESCE(benchmark_suite_id, '') WHERE benchmark_suite_id IS NULL")
            conn.execute("UPDATE jobs SET benchmark_truth_id = COALESCE(benchmark_truth_id, '') WHERE benchmark_truth_id IS NULL")
            conn.execute("UPDATE jobs SET benchmark_params_json = COALESCE(benchmark_params_json, '{}') WHERE benchmark_params_json IS NULL")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_updated ON jobs(status, updated_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_benchmark_suite ON jobs(benchmark_suite_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_benchmark_suite_truth ON benchmark_suites(truth_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_benchmark_result_suite ON benchmark_result(suite_id)")
