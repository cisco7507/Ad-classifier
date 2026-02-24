from pathlib import Path

import pytest

from video_service.core.category_mapping import load_category_mapping, select_mapping_input_text

pytestmark = pytest.mark.unit


def test_load_category_mapping_uses_explicit_columns_and_normalizes_whitespace(tmp_path: Path):
    csv_path = tmp_path / "categories.csv"
    csv_path.write_text(
        "ID,Freewheel Industry Category\n"
        " 1 ,  Agriculture   Crop Production  \n"
        "2,Agriculture Livestock Production\n",
        encoding="utf-8",
    )

    mapping_state = load_category_mapping(str(csv_path))

    assert mapping_state.enabled is True
    assert mapping_state.count == 2
    assert mapping_state.category_to_id["Agriculture Crop Production"] == "1"
    assert mapping_state.category_to_id["Agriculture Livestock Production"] == "2"
    assert mapping_state.last_error is None


def test_load_category_mapping_disables_when_required_columns_missing(tmp_path: Path):
    csv_path = tmp_path / "bad_categories.csv"
    csv_path.write_text(
        "WrongID,WrongCategory\n1,Anything\n",
        encoding="utf-8",
    )

    mapping_state = load_category_mapping(str(csv_path))

    assert mapping_state.enabled is False
    assert mapping_state.count == 0
    assert mapping_state.last_error is not None
    assert "missing required columns" in mapping_state.last_error


def test_select_mapping_input_text_fallback_order():
    assert (
        select_mapping_input_text(
            raw_category="Unknown",
            suggested_categories_text="A, B, C",
            predicted_brand="BrandX",
            ocr_summary="OCR text",
        )
        == "A, B, C"
    )
    assert (
        select_mapping_input_text(
            raw_category="none",
            suggested_categories_text="",
            predicted_brand="BrandX",
            ocr_summary="OCR text",
        )
        == "BrandX"
    )
    assert (
        select_mapping_input_text(
            raw_category="n/a",
            suggested_categories_text="",
            predicted_brand="unknown",
            ocr_summary="  Long OCR summary text  ",
        )
        == "Long OCR summary text"
    )
