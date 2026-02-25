import numpy as np
import pytest

from video_service.core import video_io

pytestmark = pytest.mark.unit


def test_extract_frames_for_pipeline_respects_scan_mode(monkeypatch):
    created = []

    class _FakeCap:
        def __init__(self):
            self.positions = []

        def isOpened(self):
            return True

        def get(self, prop):
            if prop == video_io.cv2.CAP_PROP_FPS:
                return 10.0
            if prop == video_io.cv2.CAP_PROP_FRAME_COUNT:
                return 100.0
            return 0.0

        def set(self, prop, val):
            if prop == video_io.cv2.CAP_PROP_POS_FRAMES:
                self.positions.append(int(val))

        def read(self):
            return True, np.zeros((2, 2, 3), dtype=np.uint8)

        def release(self):
            return None

    def _video_capture(_url):
        cap = _FakeCap()
        created.append(cap)
        return cap

    monkeypatch.setattr(video_io.cv2, "VideoCapture", _video_capture)
    monkeypatch.setattr(video_io, "get_stream_url", lambda u: u)

    tail_frames, _ = video_io.extract_frames_for_pipeline("dummy.mp4", scan_mode="Tail Only")
    full_frames, _ = video_io.extract_frames_for_pipeline("dummy.mp4", scan_mode="Full Video")

    tail_cap, full_cap = created
    assert tail_cap.positions == [70, 86]
    assert full_cap.positions == [0, 20, 40, 60, 80]
    assert all(frame["type"] == "tail" for frame in tail_frames)
    assert all(frame["type"] == "scene" for frame in full_frames)
    assert len(full_frames) > len(tail_frames)
