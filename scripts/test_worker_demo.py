import requests
import time
import sys

def main():
    print("Submitting Pipeline Job...")
    res = requests.post("http://127.0.0.1:8000/jobs/by-urls", json={
        "mode": "pipeline",
        "urls": ["https://www.youtube.com/watch?v=M7FIvfx5J10"],
        "settings": {
            "categories": "Automotive, Technology, Food",
            "provider": "Gemini CLI",
            "model_name": "Gemini CLI Default",
            "ocr_engine": "EasyOCR",
            "ocr_mode": "🚀 Fast",
            "scan_mode": "Tail Only",
            "override": False,
            "enable_search": False,
            "enable_vision": False,
            "context_size": 8192,
            "workers": 1
        }
    })
    job_id = res.json()[0]['job_id']
    print(f"Got Job ID: {job_id}")

    print("Polling status...")
    while True:
        st = requests.get(f"http://127.0.0.1:8000/jobs/{job_id}").json()
        status = st['status']
        print(f"Status: {status}")
        if status in ['completed', 'failed']:
            break
        time.sleep(2)
        
    print(f"Final pipeline result:")
    print(requests.get(f"http://127.0.0.1:8000/jobs/{job_id}/result").json())
    
    # Do agent test
    print("\n\nSubmitting Agent Job...")
    res = requests.post("http://127.0.0.1:8000/jobs/by-urls", json={
        "mode": "agent",
        "urls": ["https://www.youtube.com/watch?v=M7FIvfx5J10"],
        "settings": {
            "categories": "Automotive, Technology, Food",
            "provider": "Gemini CLI",
            "model_name": "Gemini CLI Default",
            "ocr_engine": "EasyOCR",
            "ocr_mode": "🚀 Fast",
            "scan_mode": "Tail Only",
            "override": False,
            "enable_search": False,
            "enable_vision": False,
            "context_size": 8192,
            "workers": 1
        }
    })
    agent_id = res.json()[0]['job_id']
    print(f"Got Agent Job ID: {agent_id}")

    print("Polling agent status...")
    while True:
        st = requests.get(f"http://127.0.0.1:8000/jobs/{agent_id}").json()
        status = st['status']
        print(f"Status: {status}")
        if status in ['completed', 'failed']:
            break
        time.sleep(4)
        
    print(f"Final agent events:")
    print(requests.get(f"http://127.0.0.1:8000/jobs/{agent_id}/events").json())

    print(f"Final agent result:")
    print(requests.get(f"http://127.0.0.1:8000/jobs/{agent_id}/result").json())


if __name__ == "__main__":
    main()
