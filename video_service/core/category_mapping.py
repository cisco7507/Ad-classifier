import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from video_service.core.utils import logger

ID_COLUMN = "ID"
CATEGORY_COLUMN = "Freewheel Industry Category"
REQUIRED_COLUMNS = (ID_COLUMN, CATEGORY_COLUMN)
DEFAULT_CATEGORY_CSV_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "categories.csv"
).resolve()
UNKNOWN_CATEGORY_VALUES = {"unknown", "none", "n/a", "n-a", ""}
_critical_messages_logged: set[str] = set()


def normalize_whitespace(value: str) -> str:
    return " ".join(str(value).split())


def _log_critical_once(message: str) -> None:
    if message in _critical_messages_logged:
        return
    logger.critical(message)
    _critical_messages_logged.add(message)


def select_mapping_input_text(
    raw_category: str,
    suggested_categories_text: str = "",
    predicted_brand: str = "",
    ocr_summary: str = "",
    ocr_max_chars: int = 400,
) -> str:
    raw_norm = normalize_whitespace(raw_category)
    if raw_norm.lower() not in UNKNOWN_CATEGORY_VALUES:
        return raw_norm

    brand_norm = normalize_whitespace(predicted_brand)
    if brand_norm.lower() not in UNKNOWN_CATEGORY_VALUES:
        return brand_norm

    ocr_norm = normalize_whitespace(ocr_summary)
    if ocr_norm:
        return ocr_norm[:ocr_max_chars]

    # Keep mapping non-empty when taxonomy is enabled.
    return "unknown"


@dataclass(frozen=True)
class CategoryMappingState:
    enabled: bool
    category_to_id: Dict[str, str]
    csv_path_used: str
    last_error: Optional[str]

    @property
    def count(self) -> int:
        return len(self.category_to_id)

    def diagnostics(self) -> dict:
        return {
            "category_mapping_enabled": self.enabled,
            "category_mapping_count": self.count,
            "category_csv_path_used": self.csv_path_used,
            "last_error": self.last_error,
        }


def resolve_category_csv_path(csv_path: Optional[str] = None) -> Path:
    env_path = os.environ.get("CATEGORY_CSV_PATH")
    chosen = csv_path or env_path or str(DEFAULT_CATEGORY_CSV_PATH)
    return Path(chosen).expanduser().resolve()


def load_category_mapping(csv_path: Optional[str] = None) -> CategoryMappingState:
    path = resolve_category_csv_path(csv_path)
    path_str = str(path)

    if not path.exists():
        error = f"category mapper disabled: CSV not found at '{path_str}'"
        _log_critical_once(error)
        return CategoryMappingState(
            enabled=False,
            category_to_id={},
            csv_path_used=path_str,
            last_error=error,
        )

    try:
        df = pd.read_csv(path, dtype=str)
    except Exception as exc:
        error = f"category mapper disabled: failed to read CSV at '{path_str}': {exc}"
        _log_critical_once(error)
        return CategoryMappingState(
            enabled=False,
            category_to_id={},
            csv_path_used=path_str,
            last_error=error,
        )

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        error = (
            f"category mapper disabled: missing required columns {missing} "
            f"in '{path_str}' (required={list(REQUIRED_COLUMNS)})"
        )
        _log_critical_once(error)
        return CategoryMappingState(
            enabled=False,
            category_to_id={},
            csv_path_used=path_str,
            last_error=error,
        )

    cat_df = df[[ID_COLUMN, CATEGORY_COLUMN]].copy()
    cat_df[ID_COLUMN] = cat_df[ID_COLUMN].astype(str).map(normalize_whitespace)
    cat_df[CATEGORY_COLUMN] = cat_df[CATEGORY_COLUMN].astype(str).map(normalize_whitespace)
    cat_df = cat_df[(cat_df[ID_COLUMN] != "") & (cat_df[CATEGORY_COLUMN] != "")]

    category_to_id = dict(zip(cat_df[CATEGORY_COLUMN], cat_df[ID_COLUMN]))
    logger.info(
        "category mapper enabled: loaded %d rows from %s",
        len(category_to_id),
        path_str,
    )
    return CategoryMappingState(
        enabled=True,
        category_to_id=category_to_id,
        csv_path_used=path_str,
        last_error=None,
    )


CATEGORY_MAPPING_STATE = load_category_mapping()


def get_category_mapping_diagnostics() -> dict:
    return CATEGORY_MAPPING_STATE.diagnostics()
