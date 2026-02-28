import sys
import types

import pytest
import torch

# `video_service.core.llm` imports `ddgs`; stub it for unit tests.
if "ddgs" not in sys.modules:
    ddgs_stub = types.ModuleType("ddgs")
    ddgs_stub.DDGS = object
    sys.modules["ddgs"] = ddgs_stub

from video_service.core import agent as agent_module

pytestmark = pytest.mark.unit


def test_run_agent_job_accepts_intermediate_six_field_agent_outputs(monkeypatch):
    monkeypatch.setattr(agent_module, "resolve_urls", lambda src, urls, fldr: ["https://example.test/video.mp4"])
    monkeypatch.setattr(
        agent_module,
        "extract_frames_for_agent",
        lambda url, **kwargs: ([{"ocr_image": object(), "image": object(), "time": 0.0}], None),
    )

    class _DummyOCR:
        @staticmethod
        def extract_text(engine, image, mode):
            return "sample ocr"

    class _DummyMapper:
        @staticmethod
        def get_nebula_plot(*args, **kwargs):
            return None

    monkeypatch.setattr(agent_module, "ocr_manager", _DummyOCR())
    monkeypatch.setattr(agent_module, "category_mapper", _DummyMapper())
    monkeypatch.setattr(agent_module.time, "sleep", lambda *_: None)

    class _DummyAgent:
        def run(self, *args, **kwargs):
            # Intermediate "thinking" output (legacy 6-field shape).
            yield ("thinking", "Unknown", "Unknown", "", "N/A", "in progress")
            # Final output (8-field shape).
            yield ("final", "BrandX", "Auto", "42", "N/A", "done", "embeddings", 0.98)

    monkeypatch.setattr(agent_module, "AdClassifierAgent", lambda: _DummyAgent())

    gen = agent_module.run_agent_job(
        src="Web URLs",
        urls="https://example.test/video.mp4",
        fldr="",
        cats="Auto",
        p="Ollama",
        m="qwen3-vl:8b-instruct",
        oe="EasyOCR",
        om="🚀 Fast",
        override=False,
        sm="Tail Only",
        enable_search=False,
        enable_vision=False,
        ctx=8192,
        job_id="job-1",
        stage_callback=None,
    )
    outputs = list(gen)

    # Initial processing + at least one intermediate + final dataframe output.
    assert len(outputs) >= 3
    final_df = outputs[-1][2]
    assert not final_df.empty
    assert final_df.iloc[0]["Brand"] == "BrandX"
    assert final_df.iloc[0]["Category ID"] == "42"


def test_ensure_react_vision_ready_builds_text_features(monkeypatch):
    class _DummyMapper:
        categories = ["Category Alpha"]
        vision_text_features = None

    class _DummyTextInputs(dict):
        def to(self, _device):
            return self

    class _DummyProcessor:
        def __call__(self, **kwargs):
            assert "text" in kwargs
            return _DummyTextInputs({"input_ids": torch.tensor([[1, 2, 3]])})

    class _DummyModel:
        @staticmethod
        def get_text_features(**kwargs):
            class _Output:
                pooler_output = torch.tensor([[1.0, 2.0, 3.0]], dtype=torch.float32)

            return _Output()

    dummy_mapper = _DummyMapper()
    monkeypatch.setattr(agent_module, "category_mapper", dummy_mapper)
    monkeypatch.setattr(agent_module, "siglip_model", _DummyModel())
    monkeypatch.setattr(agent_module, "siglip_processor", _DummyProcessor())

    assert agent_module._ensure_react_vision_ready() is True
    assert dummy_mapper.vision_text_features is not None
    assert tuple(dummy_mapper.vision_text_features.shape) == (1, 3)


def test_ensure_react_vision_ready_uses_runtime_siglip_handles(monkeypatch):
    class _DummyMapper:
        categories = ["Category Alpha"]
        vision_text_features = None

        @staticmethod
        def ensure_vision_text_features():
            return True, "ready"

    dummy_mapper = _DummyMapper()
    monkeypatch.setattr(agent_module, "category_mapper", dummy_mapper)
    monkeypatch.setattr(agent_module, "siglip_model", None)
    monkeypatch.setattr(agent_module, "siglip_processor", None)
    monkeypatch.setattr(agent_module.categories_runtime, "siglip_model", object())
    monkeypatch.setattr(agent_module.categories_runtime, "siglip_processor", object())

    assert agent_module._ensure_react_vision_ready() is True


def test_react_agent_run_emits_delta_logs_not_full_memory_repeats(monkeypatch):
    class _DummyMapper:
        categories = ["Category Alpha"]

        @staticmethod
        def map_category(**kwargs):
            return {
                "canonical_category": "Category Alpha",
                "category_id": "10",
                "category_match_method": "embeddings",
                "category_match_score": 0.99,
            }

    class _DummyOCR:
        @staticmethod
        def extract_text(engine, image, mode):
            return "VOLVO"

    responses = iter(
        [
            "[TOOL: OCR]",
            '[TOOL: FINAL | brand="Volvo" category="Category Alpha" reason="Detected brand"]',
        ]
    )

    monkeypatch.setattr(agent_module, "category_mapper", _DummyMapper())
    monkeypatch.setattr(agent_module, "ocr_manager", _DummyOCR())
    monkeypatch.setattr(
        agent_module.llm_engine,
        "query_agent",
        lambda *args, **kwargs: next(responses),
    )

    frames = [{"image": object(), "ocr_image": object(), "time": 0.0}]
    outputs = list(
        agent_module.AdClassifierAgent(max_iterations=3).run(
            frames_data=frames,
            categories=["Category Alpha"],
            provider="Ollama",
            model="qwen3-vl:8b-instruct",
            ocr_engine="EasyOCR",
            ocr_mode="🚀 Fast",
            allow_override=False,
            enable_search=False,
            enable_vision=False,
            context_size=8192,
            job_id="job-1",
            ocr_summary="VOLVO",
        )
    )

    logs = [o[0] for o in outputs]
    assert logs[0].startswith("Initial State:")
    assert sum("Initial State:" in l for l in logs) == 1
    assert any(l.startswith("--- Step 1 ---") for l in logs)
    assert any("✅ FINAL CONCLUSION REACHED." in l for l in logs)
    assert any("Observation: VOLVO" in l for l in logs)
    assert all("[Scene" not in l for l in logs)

    final = outputs[-1]
    assert final[1] == "Volvo"
    assert final[2] == "Category Alpha"
    assert final[3] == "10"
