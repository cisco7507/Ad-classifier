import logging
import os
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar, Token

_job_id_var: ContextVar[str] = ContextVar("job_id", default="-")
_stage_var: ContextVar[str] = ContextVar("stage", default="-")
_stage_detail_var: ContextVar[str] = ContextVar("stage_detail", default="-")

_configured = False
_env_loaded = False
_debug_enabled = False

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
_FORCE_QUIET_LOGGERS = (
    "httpx",
    "httpcore",
    "httpcore.http11",
    "urllib3",
    "huggingface_hub",
    "transformers",
    "sentence_transformers",
)
_FORCE_ERROR_LOGGERS = (
    # Transformers emits a warning_once call in this module using a non-format
    # argument shape that can trigger logging TypeError on Python 3.14.
    "transformers.modeling_attn_mask_utils",
    # Florence remote model load report warnings are noisy and not actionable
    # for runtime job observability.
    "transformers.modeling_utils",
)


class ContextEnricherFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = _job_id_var.get() or "-"
        record.stage = _stage_var.get() or "-"
        record.stage_detail = _stage_detail_var.get() or "-"
        return True


class NoisyLibraryFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # In DEBUG mode, allow all logs through.
        if _debug_enabled:
            return True
        # In INFO/WARNING/ERROR modes, suppress verbose library chatter.
        if record.levelno >= logging.WARNING:
            return True
        return not any(
            record.name == name or record.name.startswith(f"{name}.")
            for name in _NOISY_LOGGERS
        )


def configure_logging(force: bool = False) -> None:
    global _configured, _env_loaded, _debug_enabled
    if _configured and not force:
        return

    # Load repository .env once and make it authoritative for local app startup.
    # This keeps behavior deterministic across shells that may have stale exports.
    if not _env_loaded:
        try:
            from dotenv import load_dotenv

            repo_root = Path(__file__).resolve().parents[2]
            load_dotenv(dotenv_path=repo_root / ".env", override=True)
        except Exception:
            # Keep logging setup resilient even if python-dotenv is unavailable.
            pass
        _env_loaded = True

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper().strip()
    level = getattr(logging, level_name, logging.INFO)
    _debug_enabled = level <= logging.DEBUG

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
    noisy_filter = NoisyLibraryFilter()
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, ContextEnricherFilter) for f in handler.filters):
            handler.addFilter(context_filter)
        if not any(isinstance(f, NoisyLibraryFilter) for f in handler.filters):
            handler.addFilter(noisy_filter)

    if level > logging.DEBUG:
        for logger_name in _NOISY_LOGGERS:
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        # Hard-gate especially noisy HTTP/model loggers so DEBUG cannot leak through
        # from external logger reconfiguration later in startup.
        for logger_name in _FORCE_QUIET_LOGGERS:
            noisy_logger = logging.getLogger(logger_name)
            noisy_logger.setLevel(logging.WARNING)
            noisy_logger.propagate = False
            noisy_logger.handlers.clear()
            hard_handler = logging.StreamHandler()
            hard_handler.setLevel(logging.WARNING)
            hard_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
            hard_handler.addFilter(context_filter)
            noisy_logger.addHandler(hard_handler)

        for logger_name in _FORCE_ERROR_LOGGERS:
            err_logger = logging.getLogger(logger_name)
            err_logger.setLevel(logging.ERROR)
            err_logger.propagate = False
            err_logger.handlers.clear()
            err_handler = logging.StreamHandler()
            err_handler.setLevel(logging.ERROR)
            err_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
            err_handler.addFilter(context_filter)
            err_logger.addHandler(err_handler)

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
