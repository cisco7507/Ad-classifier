import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar, Token

_job_id_var: ContextVar[str] = ContextVar("job_id", default="-")
_stage_var: ContextVar[str] = ContextVar("stage", default="-")
_stage_detail_var: ContextVar[str] = ContextVar("stage_detail", default="-")

_configured = False

_NOISY_LOGGERS = (
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "httpx",
    "httpcore",
    "urllib3",
    "transformers",
    "sentence_transformers",
    "PIL",
    "matplotlib",
)


class ContextEnricherFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = _job_id_var.get() or "-"
        record.stage = _stage_var.get() or "-"
        record.stage_detail = _stage_detail_var.get() or "-"
        return True


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper().strip()
    level = getattr(logging, level_name, logging.INFO)

    fmt = "%(asctime)s %(levelname)-8s job_id=%(job_id)s stage=%(stage)s %(name)s %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format=fmt, datefmt=datefmt)
    else:
        root.setLevel(level)
        formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)
        for handler in root.handlers:
            handler.setFormatter(formatter)

    context_filter = ContextEnricherFilter()
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, ContextEnricherFilter) for f in handler.filters):
            handler.addFilter(context_filter)

    if level > logging.DEBUG:
        for logger_name in _NOISY_LOGGERS:
            logging.getLogger(logger_name).setLevel(logging.WARNING)

    _configured = True


def set_job_context(job_id: str) -> Token:
    return _job_id_var.set(job_id or "-")


def reset_job_context(token: Token | None = None) -> None:
    if token is not None:
        _job_id_var.reset(token)
    else:
        _job_id_var.set("-")


def set_stage_context(stage: str, stage_detail: str = "") -> tuple[Token, Token]:
    stage_token = _stage_var.set(stage or "-")
    detail_token = _stage_detail_var.set(stage_detail or "-")
    return stage_token, detail_token


def reset_stage_context(tokens: tuple[Token, Token] | None = None) -> None:
    if tokens is not None:
        stage_token, detail_token = tokens
        _stage_var.reset(stage_token)
        _stage_detail_var.reset(detail_token)
    else:
        _stage_var.set("-")
        _stage_detail_var.set("-")


@contextmanager
def job_context(job_id: str):
    token = set_job_context(job_id)
    try:
        yield
    finally:
        reset_job_context(token)

