# Events transport

Option A (simple): Poll /jobs/{id} every 1-2s; poll /jobs/{id}/events for new agent log lines.
Option B: WebSocket/SSE for /jobs/{id}/events (agent mode), polling for pipeline mode.
