import logging
from typing import Any, MutableMapping

logger = logging.getLogger(__name__)

# This holds a reference to a shared dictionary (e.g. multiprocessing.Manager().dict())
# or a standard local dictionary if running in a single process.
_aborted_jobs: MutableMapping[str, Any] | None = None


def init_abort_state(shared_dict: MutableMapping[str, Any]) -> None:
    """Initialize the global abort tracking with a provided dictionary."""
    global _aborted_jobs
    _aborted_jobs = shared_dict


def mark_job_aborted(job_id: str) -> None:
    """Mark a specific job ID as aborted."""
    if _aborted_jobs is not None:
        _aborted_jobs[job_id] = True
        logger.info("job_aborted_signal: marked %s for immediate termination", job_id)
    else:
        logger.warning("abort_state_not_initialized: cannot abort %s", job_id)


def is_job_aborted(job_id: str) -> bool:
    """Check if the given job ID has been aborted."""
    if _aborted_jobs is not None:
        return _aborted_jobs.get(job_id, False)
    return False


def clear_aborted_job(job_id: str) -> None:
    """Remove a job ID from the abort tracking to free memory."""
    if _aborted_jobs is not None:
        # pop() to avoid KeyError if it was already cleared or never added
        _aborted_jobs.pop(job_id, None)
