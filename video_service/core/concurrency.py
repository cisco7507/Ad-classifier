import logging
import os

logger = logging.getLogger(__name__)


def _parse_positive_int(env_name: str, default: int) -> int:
    raw = os.environ.get(env_name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        logger.warning("%s=%r is invalid; using %d", env_name, raw, default)
        return default
    if value < 1:
        logger.warning("%s=%r must be >= 1; using %d", env_name, raw, default)
        return default
    return value


def get_worker_processes_config() -> int:
    return _parse_positive_int("WORKER_PROCESSES", default=1)


def get_pipeline_threads_per_job() -> int:
    return _parse_positive_int("PIPELINE_THREADS_PER_JOB", default=1)


def get_concurrency_diagnostics() -> dict:
    worker_processes = get_worker_processes_config()
    pipeline_threads = get_pipeline_threads_per_job()
    return {
        "worker_processes_configured": worker_processes,
        "pipeline_threads_per_job": pipeline_threads,
        "effective_mode": (
            f"up to {worker_processes} concurrent job(s) per node; "
            f"{pipeline_threads} pipeline thread(s) per job"
        ),
    }
