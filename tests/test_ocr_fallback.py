import numpy as np
import pytest
from transformers.configuration_utils import PretrainedConfig

from video_service.core import ocr as ocr_module

pytestmark = pytest.mark.unit


def test_florence_config_compat_shim_sets_forced_bos_token_id(monkeypatch):
    monkeypatch.delattr(PretrainedConfig, "forced_bos_token_id", raising=False)

    mgr = ocr_module.OCRManager()
    mgr._ensure_florence_config_compat()

    assert hasattr(PretrainedConfig, "forced_bos_token_id")
    assert getattr(PretrainedConfig, "forced_bos_token_id") is None


def test_florence_init_failure_falls_back_to_easyocr(monkeypatch):
    class _DummyReader:
        def readtext(self, _image_rgb, detail=1):
            assert detail == 1
            return [(
                [(0, 0), (10, 0), (10, 10), (0, 10)],
                "fallback-ocr",
                0.99,
            )]

    monkeypatch.setattr(
        ocr_module.easyocr,
        "Reader",
        lambda *args, **kwargs: _DummyReader(),
    )
    monkeypatch.setattr(
        ocr_module.OCRManager,
        "_build_florence_engine",
        lambda self: (_ for _ in ()).throw(
            AttributeError("'Florence2LanguageConfig' object has no attribute 'forced_bos_token_id'")
        ),
    )

    mgr = ocr_module.OCRManager()
    image = np.zeros((32, 32, 3), dtype=np.uint8)

    text = mgr.extract_text("Florence-2 (Microsoft)", image, mode="🚀 Fast")
    assert "fallback-ocr" in text
    assert mgr.florence_unavailable_reason is not None

    # Subsequent Florence requests should not attempt Florence init again.
    before = mgr.florence_unavailable_reason
    text2 = mgr.extract_text("Florence-2 (Microsoft)", image, mode="🚀 Fast")
    assert "fallback-ocr" in text2
    assert mgr.florence_unavailable_reason == before
