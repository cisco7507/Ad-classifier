import os
import sys
import numpy as np
import pytest
from transformers.configuration_utils import PretrainedConfig
from transformers.tokenization_utils_base import PreTrainedTokenizerBase

from video_service.core import ocr as ocr_module

pytestmark = pytest.mark.unit


def test_florence_config_compat_shim_sets_forced_bos_token_id(monkeypatch):
    monkeypatch.delattr(PretrainedConfig, "forced_bos_token_id", raising=False)

    mgr = ocr_module.OCRManager()
    mgr._ensure_florence_config_compat()

    assert hasattr(PretrainedConfig, "forced_bos_token_id")
    assert getattr(PretrainedConfig, "forced_bos_token_id") is None


def test_florence_tokenizer_compat_shim_adds_additional_special_tokens(monkeypatch):
    monkeypatch.delattr(PreTrainedTokenizerBase, "additional_special_tokens", raising=False)

    mgr = ocr_module.OCRManager()
    mgr._ensure_florence_tokenizer_compat()
    assert hasattr(PreTrainedTokenizerBase, "additional_special_tokens")

    class _DummyTokenizer:
        def __init__(self):
            self.special_tokens_map = {}

        def add_special_tokens(self, payload):
            self.special_tokens_map.update(payload)

    tok = _DummyTokenizer()
    prop = PreTrainedTokenizerBase.additional_special_tokens
    assert prop.fget(tok) == []
    prop.fset(tok, ["<loc_1>", "<loc_2>"])
    assert prop.fget(tok) == ["<loc_1>", "<loc_2>"]


def test_florence_build_uses_eager_attention_and_flash_guard(monkeypatch):
    captured = {}
    state = {"processor_calls": 0}

    class _DummyModel:
        def to(self, _device):
            return self

        def eval(self):
            return self

    def _fake_model_loader(*args, **kwargs):
        captured["model_args"] = args
        captured["model_kwargs"] = kwargs
        captured["flash_env_during_load"] = os.environ.get("FLASH_ATTN_DISABLED")
        captured["flash_module_during_load"] = sys.modules.get("flash_attn", "MISSING")
        return _DummyModel()

    def _fake_processor_loader(*args, **kwargs):
        state["processor_calls"] += 1
        if state["processor_calls"] == 1:
            raise RuntimeError("first attempt failed; retry fallback path")
        captured["processor_args"] = args
        captured["processor_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(ocr_module.AutoModelForCausalLM, "from_pretrained", _fake_model_loader)
    monkeypatch.setattr(ocr_module.AutoProcessor, "from_pretrained", _fake_processor_loader)
    monkeypatch.delenv("FLASH_ATTN_DISABLED", raising=False)
    monkeypatch.delitem(sys.modules, "flash_attn", raising=False)

    mgr = ocr_module.OCRManager()
    engine = mgr._build_florence_engine()

    assert engine["type"] == "florence2"
    assert captured["model_kwargs"]["attn_implementation"] == "eager"
    assert captured["model_kwargs"]["trust_remote_code"] is True
    assert captured["flash_env_during_load"] == "1"
    assert captured["flash_module_during_load"] is None
    assert captured["processor_kwargs"]["trust_remote_code"] is True
    assert state["processor_calls"] == 2
    assert "use_fast" not in captured["processor_kwargs"]
    assert os.environ.get("FLASH_ATTN_DISABLED") is None
    assert "flash_attn" not in sys.modules


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
