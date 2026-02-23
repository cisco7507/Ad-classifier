#!/usr/bin/env bash
set -e

source venv/bin/activate

echo "Starting Uvicorn..."
uvicorn video_service.app.main:app --host 127.0.0.1 --port 8000 &
UVICORN_PID=$!

echo "Starting Worker..."
python video_service/workers/worker.py &
WORKER_PID=$!

sleep 2

echo "Submitting job..."
RESPONSE=$(curl -s -X POST "http://127.0.0.1:8000/jobs" -H "Content-Type: application/json" -d '{"url":"http://example.com"}')
echo "Response: $RESPONSE"
JOB_ID=$(echo $RESPONSE | grep -o 'node-[a-zA-Z0-9-]*')

echo "Polling job status for $JOB_ID..."
for i in {1..10}; do
    STATUS_RESP=$(curl -s "http://127.0.0.1:8000/jobs/$JOB_ID")
    echo "Status: $STATUS_RESP"
    if echo "$STATUS_RESP" | grep -q '"status":"completed"'; then
        echo "Job completed successfully!"
        kill $UVICORN_PID
        kill $WORKER_PID
        exit 0
    fi
    sleep 1
done

echo "Job did not complete in time."
kill $UVICORN_PID
kill $WORKER_PID
exit 1
