import logging

import pytest

from video_service.core import logging_setup

pytestmark = pytest.mark.unit


def _record(name: str, level: int) -> logging.LogRecord:
    return logging.LogRecord(name=name, level=level, pathname=__file__, lineno=1, msg="x", args=(), exc_info=None)


def test_noisy_filter_suppresses_httpcore_debug_when_not_debug(monkeypatch):
    monkeypatch.setattr(logging_setup, "_debug_enabled", False)
    filt = logging_setup.NoisyLibraryFilter()
    assert filt.filter(_record("httpcore.http11", logging.DEBUG)) is False
    assert filt.filter(_record("httpx", logging.INFO)) is False
    assert filt.filter(_record("httpcore.http11", logging.WARNING)) is True
    assert filt.filter(_record("video_service.core", logging.INFO)) is True


def test_noisy_filter_allows_noisy_debug_in_debug_mode(monkeypatch):
    monkeypatch.setattr(logging_setup, "_debug_enabled", True)
    filt = logging_setup.NoisyLibraryFilter()
    assert filt.filter(_record("httpcore.http11", logging.DEBUG)) is True


def test_configure_logging_hard_gates_httpcore_when_not_debug(monkeypatch):
    monkeypatch.setattr(logging_setup, "_configured", False)
    monkeypatch.setattr(logging_setup, "_env_loaded", True)
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    logging_setup.configure_logging()

    httpcore_logger = logging.getLogger("httpcore")
    assert httpcore_logger.level == logging.WARNING
    assert httpcore_logger.propagate is False
    assert httpcore_logger.handlers
    assert httpcore_logger.handlers[0].level == logging.WARNING


def test_configure_logging_force_reapplies_after_mutation(monkeypatch):
    monkeypatch.setattr(logging_setup, "_configured", False)
    monkeypatch.setattr(logging_setup, "_env_loaded", True)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    logging_setup.configure_logging()

    httpcore_logger = logging.getLogger("httpcore")
    # Simulate external logger mutation after initial setup.
    httpcore_logger.setLevel(logging.DEBUG)
    httpcore_logger.propagate = True

    logging_setup.configure_logging(force=True)
    assert httpcore_logger.level == logging.WARNING
    assert httpcore_logger.propagate is False


def test_configure_logging_repo_env_overrides_shell_log_level(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "video_service" / "core").mkdir(parents=True)
    (repo_root / ".env").write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
    fake_file = repo_root / "video_service" / "core" / "logging_setup.py"
    fake_file.write_text("# test\n", encoding="utf-8")

    monkeypatch.setattr(logging_setup, "__file__", str(fake_file))
    monkeypatch.setattr(logging_setup, "_configured", False)
    monkeypatch.setattr(logging_setup, "_env_loaded", False)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    logging_setup.configure_logging(force=True)
    assert logging.getLogger().level == logging.INFO
