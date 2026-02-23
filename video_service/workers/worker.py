import time
import os
import sys

# ensure video_service is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from video_service.db.database import get_db, init_db

def claim_and_process_job():
    conn = get_db()
    try:
        cur = conn.cursor()
        
        # Simple atomic claim if using SQLite without heavy concurrency:
        # Instead of SELECT then UPDATE (which requires explicit transaction/locking in SQLite),
        # we can UPDATE with RETURNING if sqlite >= 3.35, but let's do a basic begin exclusive.
        
        conn.execute("BEGIN EXCLUSIVE")
        
        cur.execute("SELECT id FROM jobs WHERE status = 'queued' LIMIT 1")
        row = cur.fetchone()
        
        if not row:
            conn.rollback()
            return False
            
        job_id = row['id']
        cur.execute("UPDATE jobs SET status = 'processing', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
        conn.commit()
        
        print(f"Worker claimed job: {job_id}", flush=True)
        
        # Simulate video processing
        time.sleep(1)
        
        with get_db() as update_conn:
            update_conn.execute("UPDATE jobs SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
            
        print(f"Worker completed job: {job_id}", flush=True)
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"Worker encounter an error: {e}", flush=True)
        return False

def run_worker():
    print("Worker started. Waiting for jobs...", flush=True)
    init_db()
    while True:
        processed = claim_and_process_job()
        if not processed:
            time.sleep(1)

if __name__ == "__main__":
    run_worker()
