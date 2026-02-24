curl -X POST http://127.0.0.1:8000/jobs/by-urls \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pipeline",
    "urls": [
      "https://video.adsoftheworld.com/bzoe961keml3r4b5uo66q1gftv9m.mp4"
    ],
    "settings": {
      "categories": "",
      "provider": "Ollama",
      "model_name": "qwen3-vl:8b-instruct",
      "ocr_engine": "EasyOCR",
      "ocr_mode": "🚀 Fast",
      "scan_mode": "Tail Only",
      "override": false,
      "enable_search": true,
      "enable_vision": true,
      "context_size": 8192,
      "workers": 4
    }
  }'