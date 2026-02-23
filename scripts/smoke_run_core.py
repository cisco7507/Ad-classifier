import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from video_service.core import run_pipeline_job

def test_pipeline():
    url = "https://www.youtube.com/watch?v=M7FIvfx5J10"
    urls = url
    
    print("Testing Pipeline...")
    generator = run_pipeline_job(
        src="Web URLs",
        urls=urls,
        fldr="",
        cats="Automotive, Technology, Food",
        p="Gemini CLI",
        m="Gemini CLI Default",
        oe="EasyOCR",
        om="🚀 Fast",
        override=False,
        sm="Tail Only",
        enable_search=False,
        enable_vision=False,
        ctx=8192,
        workers=1
    )
    
    for v, t, d, g, df in generator:
        print(df.to_dict(orient="records"))

if __name__ == "__main__":
    test_pipeline()
    print("Smoke test finished.")
