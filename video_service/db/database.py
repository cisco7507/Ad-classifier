import sqlite3
import os


def _default_database_path() -> str:
    node_name = (os.environ.get("NODE_NAME") or "node-a").strip() or "node-a"
    return f"video_service_{node_name}.db"


DB_PATH = os.environ.get("DATABASE_PATH") or _default_database_path()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    with conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
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
