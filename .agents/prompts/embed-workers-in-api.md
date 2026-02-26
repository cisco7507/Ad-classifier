# Feature: Embed Worker Processes in the API Lifespan

## Problem

The service currently requires **two separate commands** to run:

```bash
# Terminal 1 — API
uvicorn video_service.app.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — Workers
python -m video_service.workers.worker
```

If you forget to start the worker process, submitted jobs sit in `status='queued'` forever. This is a common pitfall during development and adds deployment complexity (two containers per node in Docker Compose).

## Goal

Make a single `uvicorn` command start **both** the API server and the background worker processes. The `.env` worker settings (`WORKER_PROCESSES`, `PIPELINE_THREADS_PER_JOB`) must continue to be respected exactly as they are today.

Add an `EMBED_WORKERS` env var (default `true`) so operators can disable embedded workers and run them separately if needed.

## Architecture Context

- The API and workers share **no in-memory state**. They communicate exclusively through the SQLite `jobs` table.
- Workers run as separate OS processes via `multiprocessing.Process`, each running a polling loop (`_run_single_worker`) that claims `status='queued'` rows.
- The worker module already has a supervisor pattern (`_run_worker_supervisor`) that spawns N child processes, monitors them, and auto-restarts crashed ones.
- The API lifespan already spawns background daemon threads (cleanup thread, cluster health-check thread).

## Implementation

### 1. Add `EMBED_WORKERS` to `.env` and `.env.example`

Add this in the `── Workers` section, **before** `WORKER_PROCESSES`:

```
# When true, the API process spawns worker processes on startup.
# Set to false to run workers separately via: python -m video_service.workers.worker
EMBED_WORKERS=true
```

### 2. Create `video_service/workers/embedded.py`

This is a small module (~50 lines) that the API lifespan calls. It must:

1. Read `EMBED_WORKERS` from env. If `false`/`0`/`no`, do nothing.
2. Read `WORKER_PROCESSES` via `get_worker_processes_config()` from `video_service.core.concurrency`.
3. Spawn that many `multiprocessing.Process` children, each targeting `_run_single_worker` from `video_service.workers.worker`.
4. Start a lightweight **daemon thread** that monitors the children every 2 seconds and restarts any that have exited (mirroring the existing `_run_worker_supervisor` loop).
5. Expose a `shutdown()` function that terminates all children, joins them with a timeout, and force-kills stragglers.

```python
"""
video_service/workers/embedded.py
==================================
Spawns worker processes inside the API lifespan.
"""

import logging
import multiprocessing
import os
import threading
import time

from video_service.core.concurrency import get_worker_processes_config

logger = logging.getLogger(__name__)

_children: list[multiprocessing.Process] = []
_monitor_thread: threading.Thread | None = None
_shutdown_event = threading.Event()


def _parse_embed_workers() -> bool:
    raw = os.environ.get("EMBED_WORKERS", "true").strip().lower()
    return raw in ("1", "true", "yes")


def _worker_child_main(index: int) -> None:
    # Import here to avoid loading heavy ML libs in the API process
    from video_service.workers.worker import _run_single_worker
    logger.info("embedded_worker_start: index=%d pid=%d", index, os.getpid())
    _run_single_worker()


def _spawn_child(index: int) -> multiprocessing.Process:
    proc = multiprocessing.Process(
        target=_worker_child_main,
        kwargs={"index": index},
        name=f"embedded-worker-{index}",
        daemon=False,
    )
    return proc


def _monitor_loop() -> None:
    """Watch children; restart any that exit unexpectedly."""
    while not _shutdown_event.is_set():
        for idx in range(len(_children)):
            proc = _children[idx]
            if proc.is_alive():
                continue
            if _shutdown_event.is_set():
                return
            logger.warning(
                "embedded_worker_exited: index=%d pid=%s exit_code=%s; restarting",
                idx + 1, proc.pid, proc.exitcode,
            )
            replacement = _spawn_child(idx + 1)
            replacement.start()
            logger.info("embedded_worker_respawned: index=%d pid=%d", idx + 1, replacement.pid)
            _children[idx] = replacement
        _shutdown_event.wait(timeout=2.0)


def start() -> int:
    """Spawn embedded workers. Returns the number of processes started (0 if disabled)."""
    global _monitor_thread

    if not _parse_embed_workers():
        logger.info("embedded_workers: disabled (EMBED_WORKERS=false)")
        return 0

    process_count = get_worker_processes_config()
    logger.info("embedded_workers: spawning %d worker process(es)", process_count)

    _shutdown_event.clear()
    for index in range(1, process_count + 1):
        proc = _spawn_child(index)
        proc.start()
        logger.info("embedded_worker_spawned: index=%d pid=%d", index, proc.pid)
        _children.append(proc)

    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True, name="worker-monitor")
    _monitor_thread.start()

    return process_count


def shutdown() -> None:
    """Terminate all embedded worker processes."""
    _shutdown_event.set()

    for proc in _children:
        if proc.is_alive():
            logger.info("embedded_worker_terminate: pid=%s", proc.pid)
            proc.terminate()

    for proc in _children:
        proc.join(timeout=5.0)
        if proc.is_alive():
            logger.warning("embedded_worker_force_kill: pid=%s", proc.pid)
            proc.kill()
            proc.join(timeout=2.0)

    _children.clear()
    logger.info("embedded_workers: all workers stopped")
```

### 3. Modify `video_service/app/main.py` — the lifespan

In the existing `lifespan()` function (lines 77–88), add worker start/stop around the `yield`:

```python
# Current lifespan:
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(force=True)
    cluster.start_health_checks()
    logger.info("startup: initialising DB (node=%s)", NODE_NAME)
    init_db()
    start_cleanup_thread()
    logger.info("startup: ready (node=%s, cors_origins=%s)", NODE_NAME, CORS_ORIGINS)
    yield
    logger.info("shutdown: node=%s", NODE_NAME)


# New lifespan:
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(force=True)
    cluster.start_health_checks()
    logger.info("startup: initialising DB (node=%s)", NODE_NAME)
    init_db()
    start_cleanup_thread()

    # Spawn embedded workers (respects EMBED_WORKERS and WORKER_PROCESSES env vars)
    from video_service.workers.embedded import start as start_workers, shutdown as shutdown_workers
    worker_count = start_workers()
    if worker_count:
        logger.info("startup: %d embedded worker(s) active", worker_count)

    logger.info("startup: ready (node=%s, cors_origins=%s)", NODE_NAME, CORS_ORIGINS)
    yield

    # Graceful shutdown of embedded workers
    shutdown_workers()
    logger.info("shutdown: node=%s", NODE_NAME)
```

**Important:** The import of `video_service.workers.embedded` must be done **inside** the lifespan function (lazy import), not at module top level. This avoids importing heavy ML dependencies (torch, cv2, easyocr) into the API process at import time. The actual heavy imports only happen inside the child processes.

### 4. Update `docker-compose.yml`

Remove the `worker-a` and `worker-b` services. Add `EMBED_WORKERS` and `WORKER_PROCESSES` to the backend service environments:

```yaml
  # REMOVE this entire service block:
  # worker-a:
  #   <<: *backend-base
  #   container_name: ad-worker-a
  #   depends_on: ...
  #   environment: ...
  #   volumes: ...
  #   command: python -m video_service.workers.worker

  # Same for worker-b.
```

Add to `backend-a` and `backend-b` environment sections:

```yaml
      EMBED_WORKERS: "true"
      WORKER_PROCESSES: ${WORKER_PROCESSES:-2}
```

### 5. Keep `worker.py` standalone entry point working

Do **NOT** remove the `if __name__ == "__main__":` block in `worker.py`. It must still work for operators who set `EMBED_WORKERS=false` and run workers separately. No changes to `worker.py` are needed.

## Files to modify

| File | Changes |
|------|---------|
| `video_service/workers/embedded.py` | **New file** — worker spawner + monitor + shutdown (~90 lines) |
| `video_service/app/main.py` | Add ~8 lines in `lifespan()` to call `start()` / `shutdown()` |
| `.env` | Add `EMBED_WORKERS=true` in the Workers section |
| `.env.example` | Add `EMBED_WORKERS=true` with comment |
| `docker-compose.yml` | Remove `worker-a` and `worker-b` services; add env vars to backends |
| `Architecture.md` | Update "Runtime Topology" section to describe embedded mode |

## Constraints

- **Do NOT modify `video_service/workers/worker.py`** — import from it, don't refactor it.
- **Do NOT import torch, cv2, or any ML library at the top level of `embedded.py` or `main.py`** — they must only load inside worker child processes.
- **`WORKER_PROCESSES` and `PIPELINE_THREADS_PER_JOB` from `.env` must be respected identically** to the existing standalone worker behavior.
- **Worker processes must be spawned with `daemon=False`** so they survive if the monitor thread dies, and can be explicitly terminated during shutdown.
- **The monitor thread must be `daemon=True`** so it doesn't block Uvicorn shutdown.
- **Structured logging only** — never `print()`.
- **Type hints** on all new functions.
- **Uvicorn `--workers` must remain `1`** — document this. If `multiprocessing.parent_process() is not None`, skip worker spawning to guard against accidental forked duplicates.

## Testing checklist

1. `EMBED_WORKERS=true WORKER_PROCESSES=2` → start API, submit a job, verify it gets processed without a separate worker command.
2. `EMBED_WORKERS=false` → start API, submit a job, verify it stays `queued` until a separate `python -m video_service.workers.worker` is started.
3. Kill a worker child process (e.g., `kill <pid>`) → verify the monitor thread restarts it within ~2 seconds.
4. `Ctrl+C` the API → verify all worker processes are terminated cleanly (no orphans).
5. `WORKER_PROCESSES=1` → verify only one worker child is spawned.
6. Verify `/diagnostics/concurrency` still reports accurate values.
