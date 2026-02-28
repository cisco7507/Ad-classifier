from video_service.core.benchmarking import (
    jaccard_similarity,
    levenshtein_similarity,
    extract_stage_duration_seconds,
)


def test_jaccard_similarity_basic():
    score = jaccard_similarity(
        ["Automotive", "Road Safety"],
        ["Road Safety", "Insurance"],
    )
    assert round(score, 3) == round(1 / 3, 3)


def test_levenshtein_similarity_bounds():
    assert levenshtein_similarity("abc", "abc") == 1.0
    assert 0.0 <= levenshtein_similarity("abc", "xyz") <= 1.0


def test_extract_stage_duration_from_events():
    events = [
        "2026-02-28T12:00:00+00:00 frame_extract: extracted 5 frames",
        "2026-02-28T12:00:12+00:00 llm: calling provider",
        "2026-02-28T12:00:19+00:00 persist: persisting result payload",
    ]
    assert extract_stage_duration_seconds(events, fallback_duration=33.2) == 19.0

