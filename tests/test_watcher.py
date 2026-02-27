from video_service.core.watcher import _is_safe_watch_path, get_watcher_diagnostics


def test_is_safe_watch_path_accepts_child(tmp_path):
    root = tmp_path / "watch"
    root.mkdir()
    video = root / "ad.mp4"
    video.write_text("x", encoding="utf-8")

    assert _is_safe_watch_path(str(video), [str(root)])


def test_is_safe_watch_path_rejects_outside(tmp_path):
    root = tmp_path / "watch"
    root.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_text("x", encoding="utf-8")

    assert not _is_safe_watch_path(str(outside), [str(root)])


def test_watcher_diagnostics_reads_env(monkeypatch):
    monkeypatch.setenv("WATCH_FOLDERS", "/tmp/inbox_a,/tmp/inbox_b")
    monkeypatch.setenv("WATCH_OUTPUT_DIR", "/tmp/outbox")
    monkeypatch.setenv("WATCH_DEFAULT_MODE", "pipeline")
    monkeypatch.setenv("WATCH_STABILIZE_SECONDS", "5")

    info = get_watcher_diagnostics()

    assert info["enabled"] is True
    assert info["watch_folders"] == ["/tmp/inbox_a", "/tmp/inbox_b"]
    assert info["output_dir"] == "/tmp/outbox"
    assert info["default_mode"] == "pipeline"
    assert info["stabilize_seconds"] == 5.0
