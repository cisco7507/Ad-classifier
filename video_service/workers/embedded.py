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
from typing import Any
from logging.handlers import QueueHandler, QueueListener
from multiprocessing.managers import SyncManager

from video_service.core.concurrency import get_worker_processes_config

logger = logging.getLogger(__name__)

_children: list[multiprocessing.Process] = []
_monitor_thread: threading.Thread | None = None
_shutdown_event = threading.Event()
_log_queue: multiprocessing.Queue | None = None
_log_listener: QueueListener | None = None
_abort_manager: SyncManager | None = None
_abort_dict: Any | None = None


def _parse_embed_workers() -> bool:
    raw = os.environ.get("EMBED_WORKERS", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _worker_child_main(index: int, log_queue: multiprocessing.Queue, abort_dict: Any) -> None:
    # 1. Clear out any existing handlers inherited from the fork
    root = logging.getLogger()
    if root.handlers:
        root.handlers.clear()
        
    # 2. Pipe all worker logs to the parent process's queue
    qh = QueueHandler(log_queue)
    # We do NOT want the QueueHandler to format the string here; 
    # we want the parent to format it so it hits the MemoryListHandler identically.
    root.addHandler(qh)
    root.setLevel(logging.INFO)

    # Lazy import keeps worker ML deps out of API parent process.
    from video_service.core.abort import init_abort_state
    init_abort_state(abort_dict)

    from video_service.workers.worker import _run_single_worker

    logger.info("embedded_worker_start: index=%d pid=%d", index, os.getpid())
    _run_single_worker()


def _spawn_child(index: int) -> multiprocessing.Process:
    global _log_queue, _abort_dict
    proc = multiprocessing.Process(
        target=_worker_child_main,
        kwargs={"index": index, "log_queue": _log_queue, "abort_dict": _abort_dict},
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
    
    global _log_queue, _log_listener, _abort_manager, _abort_dict
    if _log_queue is None:
        _log_queue = multiprocessing.Queue()
        # The parent process listens to the queue and passes records physical 
        # root logger handlers (which includes MemoryListHandler for the UI)
        parent_handlers = logging.getLogger().handlers
        _log_listener = QueueListener(_log_queue, *parent_handlers, respect_handler_level=True)
        _log_listener.start()

    if _abort_manager is None:
        _abort_manager = multiprocessing.Manager()
        _abort_dict = _abort_manager.dict()
        
        from video_service.core.abort import init_abort_state
        init_abort_state(_abort_dict)

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
    
    global _log_listener, _log_queue
    if _log_listener:
        _log_listener.stop()
        _log_listener = None
    if _log_queue:
        _log_queue.close()
        _log_queue = None
        
    global _abort_manager, _abort_dict
    if _abort_manager:
        _abort_manager.shutdown()
        _abort_manager = None
        _abort_dict = None
        
    logger.info("embedded_workers: all workers stopped")

