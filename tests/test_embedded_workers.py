import importlib

import pytest

import video_service.workers.embedded as embedded

pytestmark = pytest.mark.unit


class _FakeProcess:
    _pid = 1000

    def __init__(self, *, target, kwargs, name, daemon):
        self.target = target
        self.kwargs = kwargs
        self.name = name
        self.daemon = daemon
        self.exitcode = None
        self._alive = False
        _FakeProcess._pid += 1
        self.pid = _FakeProcess._pid

    def start(self):
        self._alive = True

    def is_alive(self):
        return self._alive

    def terminate(self):
        self._alive = False
        self.exitcode = -15

    def join(self, timeout=None):
        return None

    def kill(self):
        self._alive = False
        self.exitcode = -9


class _FakeThread:
    def __init__(self, target=None, daemon=None, name=None, args=(), kwargs=None):
        self.target = target
        self.daemon = daemon
        self.name = name
        self._alive = False

    def start(self):
        self._alive = True

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self._alive = False
        return None


def _reload_module():
    return importlib.reload(embedded)


def test_start_disabled_via_env(monkeypatch):
    module = _reload_module()
    monkeypatch.setenv("EMBED_WORKERS", "false")
    monkeypatch.setattr(module.multiprocessing, "parent_process", lambda: None)

    started = module.start()

    assert started == 0
    assert module._children == []


def test_start_skips_inside_parented_process(monkeypatch):
    module = _reload_module()
    monkeypatch.setenv("EMBED_WORKERS", "true")
    monkeypatch.setattr(module.multiprocessing, "parent_process", lambda: object())

    started = module.start()

    assert started == 0
    assert module._children == []


def test_start_and_shutdown_embedded_workers(monkeypatch):
    module = _reload_module()
    monkeypatch.setenv("EMBED_WORKERS", "true")
    monkeypatch.setattr(module.multiprocessing, "parent_process", lambda: None)
    monkeypatch.setattr(module, "get_worker_processes_config", lambda: 2)
    monkeypatch.setattr(module.multiprocessing, "Process", _FakeProcess)
    monkeypatch.setattr(module.threading, "Thread", _FakeThread)

    started = module.start()
    assert started == 2
    assert len(module._children) == 2
    assert all(proc.daemon is False for proc in module._children)
    assert all(proc.is_alive() for proc in module._children)

    module.shutdown()
    assert module._children == []
