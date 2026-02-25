import pytest
import torch

from video_service.core import categories as categories_module

pytestmark = pytest.mark.unit


def test_siglip_loader_retries_processor_with_use_fast_false(monkeypatch):
    class _DummyModel:
        def to(self, _device):
            return self

    calls = []

    def _processor_side_effect(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise AttributeError("'NoneType' object has no attribute 'replace'")
        return object()

    monkeypatch.setattr(categories_module, "siglip_model", None)
    monkeypatch.setattr(categories_module, "siglip_processor", None)
    monkeypatch.setattr(
        categories_module.AutoModel,
        "from_pretrained",
        lambda *args, **kwargs: _DummyModel(),
    )
    monkeypatch.setattr(
        categories_module.AutoProcessor,
        "from_pretrained",
        _processor_side_effect,
    )

    ok = categories_module._ensure_siglip_loaded()

    assert ok is True
    assert categories_module.siglip_model is not None
    assert categories_module.siglip_processor is not None
    assert len(calls) == 2
    assert calls[0].get("use_fast") is None
    assert calls[1].get("use_fast") is False


def test_siglip_loader_falls_back_to_explicit_siglip_classes_when_auto_fails(monkeypatch):
    class _DummyModel:
        def to(self, _device):
            return self

    class _DummyProcessor:
        pass

    monkeypatch.setattr(categories_module, "siglip_model", None)
    monkeypatch.setattr(categories_module, "siglip_processor", None)
    monkeypatch.setattr(
        categories_module.AutoModel,
        "from_pretrained",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AttributeError("'NoneType' object has no attribute 'replace'")
        ),
    )
    monkeypatch.setattr(
        categories_module,
        "_load_siglip_explicit",
        lambda: (_DummyModel(), _DummyProcessor()),
    )

    ok = categories_module._ensure_siglip_loaded()

    assert ok is True
    assert isinstance(categories_module.siglip_model, _DummyModel)
    assert isinstance(categories_module.siglip_processor, _DummyProcessor)


def test_normalize_feature_tensor_accepts_pooler_output_container():
    class _Output:
        pooler_output = torch.tensor([[3.0, 4.0]], dtype=torch.float32)

    normalized = categories_module.normalize_feature_tensor(
        _Output(),
        source="SigLIP.get_text_features",
    )
    assert normalized.shape == (1, 2)
    assert torch.allclose(normalized.norm(p=2, dim=-1), torch.ones(1), atol=1e-6)
