"""
video_service/workers/embedded.py
=================================
Spawn and supervise worker child processes from inside API lifespan.
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
    return raw in {"1", "true", "yes", "on"}


def _worker_child_main(index: int) -> None:
    # Lazy import keeps worker ML deps out of API parent process.
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
    while not _shutdown_event.is_set():
        for idx, proc in enumerate(list(_children)):
            if proc.is_alive():
                continue
            if _shutdown_event.is_set():
                return

            logger.warning(
                "embedded_worker_exited: index=%d pid=%s exit_code=%s; restarting",
                idx + 1,
                proc.pid,
                proc.exitcode,
            )
            replacement = _spawn_child(idx + 1)
            replacement.start()
            logger.info(
                "embedded_worker_respawned: index=%d pid=%d",
                idx + 1,
                replacement.pid,
            )
            _children[idx] = replacement

        _shutdown_event.wait(timeout=2.0)


def start() -> int:
    """Spawn embedded worker processes. Returns number started."""
    global _monitor_thread

    if multiprocessing.parent_process() is not None:
        logger.warning(
            "embedded_workers: skipping spawn in child process; run uvicorn with --workers=1"
        )
        return 0

    if not _parse_embed_workers():
        logger.info("embedded_workers: disabled (EMBED_WORKERS=false)")
        return 0

    if _children:
        alive = sum(1 for proc in _children if proc.is_alive())
        logger.info("embedded_workers: already started (alive=%d)", alive)
        return alive

    process_count = get_worker_processes_config()
    logger.info("embedded_workers: spawning %d worker process(es)", process_count)

    _shutdown_event.clear()
    for index in range(1, process_count + 1):
        proc = _spawn_child(index)
        proc.start()
        logger.info("embedded_worker_spawned: index=%d pid=%d", index, proc.pid)
        _children.append(proc)

    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        daemon=True,
        name="embedded-worker-monitor",
    )
    _monitor_thread.start()
    return process_count


def shutdown() -> None:
    """Terminate and reap all embedded workers."""
    global _monitor_thread

    _shutdown_event.set()
    if _monitor_thread and _monitor_thread.is_alive():
        _monitor_thread.join(timeout=2.0)
    _monitor_thread = None

    for proc in list(_children):
        if proc.is_alive():
            logger.info("embedded_worker_terminate: pid=%s", proc.pid)
            proc.terminate()

    for proc in list(_children):
        proc.join(timeout=5.0)
        if proc.is_alive():
            logger.warning("embedded_worker_force_kill: pid=%s", proc.pid)
            proc.kill()
            proc.join(timeout=2.0)

    _children.clear()
    logger.info("embedded_workers: all workers stopped")

