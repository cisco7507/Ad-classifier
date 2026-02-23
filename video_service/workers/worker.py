import time
import os
import sys
import json
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from video_service.db.database import get_db, init_db
from video_service.core import run_pipeline_job, run_agent_job
from video_service.core.device import get_diagnostics, DEVICE

def claim_and_process_job():
    conn = get_db()
    try:
        cur = conn.cursor()
        conn.execute("BEGIN EXCLUSIVE")
        
        cur.execute("SELECT * FROM jobs WHERE status = 'queued' LIMIT 1")
        row = cur.fetchone()
        
        if not row:
            conn.rollback()
            return False
            
        job_id = row['id']
        cur.execute("UPDATE jobs SET status = 'processing', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
        conn.commit()
        
        print(f"Worker claimed job: {job_id} running on device: {DEVICE}", flush=True)
        
        url = row['url']
        mode = row['mode']
        settings = json.loads(row['settings']) if row['settings'] else {}
        
        events = []
        result_json = None
        error_msg = None
        
        try:
            if mode == 'pipeline':
                generator = run_pipeline_job(
                    src="Web URLs",
                    urls=url,
                    fldr="",
                    cats=settings.get("categories", ""),
                    p=settings.get("provider", "Gemini CLI"),
                    m=settings.get("model_name", "Gemini CLI Default"),
                    oe=settings.get("ocr_engine", "EasyOCR"),
                    om=settings.get("ocr_mode", "🚀 Fast"),
                    override=settings.get("override", False),
                    sm=settings.get("scan_mode", "Tail Only"),
                    enable_search=settings.get("enable_search", True),
                    enable_vision=settings.get("enable_vision", True),
                    ctx=settings.get("context_size", 8192),
                    workers=1
                )
                
                final_df = None
                for content in generator:
                    if len(content) == 5:
                        final_df = content[4]
                        
                if final_df is not None and not final_df.empty:
                    result_json = json.dumps(final_df.to_dict(orient="records"))
                    
            elif mode == 'agent':
                generator = run_agent_job(
                    src="Web URLs",
                    urls=url,
                    fldr="",
                    cats=settings.get("categories", ""),
                    p=settings.get("provider", "Gemini CLI"),
                    m=settings.get("model_name", "Gemini CLI Default"),
                    oe=settings.get("ocr_engine", "EasyOCR"),
                    om=settings.get("ocr_mode", "🚀 Fast"),
                    override=settings.get("override", False),
                    sm=settings.get("scan_mode", "Tail Only"),
                    enable_search=settings.get("enable_search", True),
                    enable_vision=settings.get("enable_vision", True),
                    ctx=settings.get("context_size", 8192)
                )
                
                final_df = None
                for content in generator:
                    if len(content) == 4:
                        log_str, gallery, df, nebula = content
                        events.append(log_str)
                        final_df = df
                        with get_db() as uconn:
                            uconn.execute("UPDATE jobs SET events = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(events), job_id))

                if final_df is not None and not final_df.empty:
                    result_json = json.dumps(final_df.to_dict(orient="records"))
                    
        except Exception as e:
            traceback.print_exc()
            error_msg = str(e)

        with get_db() as update_conn:
            if error_msg:
                update_conn.execute("UPDATE jobs SET status = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (error_msg, job_id))
                print(f"Worker failed job: {job_id} ({error_msg})", flush=True)
            else:
                update_conn.execute("UPDATE jobs SET status = 'completed', progress=100, result_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (result_json, job_id))
                print(f"Worker completed job: {job_id}", flush=True)
                
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"Worker encounter an error locking: {e}", flush=True)
        return False

def run_worker():
    print(f"Worker started. Diagnostics: {json.dumps(get_diagnostics())}", flush=True)
    init_db()
    while True:
        processed = claim_and_process_job()
        if not processed:
            time.sleep(1)

if __name__ == "__main__":
    run_worker()
