# Feature: OCR Deduplication Refinement for Smart Tail Sampling

## Prerequisite

This feature builds on top of the histogram-based static frame detection implemented in `video_service/core/video_io.py`. That feature detects visually identical tail frames (static endcards) and extends backward to capture earlier, visually different frames. **Read that code first before implementing this refinement.**

This refinement catches an edge case that histogram comparison alone misses: endcards with **subtle visual animation** (pulsing logo, progress bar, particle effects) where the pixels change frame-to-frame but the **text content** remains identical. In those cases, histogram correlation drops below the static threshold, so the backward extension never triggers — even though the OCR text is the same useless endcard text on every frame.

## Problem

Consider an endcard with an animated background but static text like "Watch more at hulu.com". The histogram correlations between frames might be 0.85 (below the 0.97 threshold) because the animation changes pixel values. But every frame produces the same OCR output: `"Watch more at hulu.com"`. The pipeline sends this single repeated phrase to the LLM, which has no brand information to work with.

## Solution: Post-OCR Text Deduplication Check

After OCR has been run on all tail frames (in `pipeline.py`'s `process_single_video`), check whether the extracted text is suspiciously homogeneous. If it is, re-invoke the frame extractor with a backward extension hint or directly extend the frame set and re-run OCR on the new frames.

## Implementation Details

### Where to implement

Changes go in **`video_service/core/pipeline.py`** inside `process_single_video`, after the OCR extraction step (currently line ~91) and before the LLM query (currently line ~94).

### Algorithm

```
1. OCR runs on tail frames as normal (line ~91), producing ocr_text.
2. Split ocr_text into per-frame lines (it's newline-delimited: "[27.0s] text here\n[28.5s] text here").
3. Extract just the text portion of each line (strip the timestamp prefix).
4. Normalize each text: lowercase, strip whitespace, remove punctuation.
5. Check if all normalized texts are "effectively identical":
   - If there are ≥2 lines AND all unique normalized texts reduce to ≤1 distinct value → OCR is static.
   - Also trigger if all texts are empty (no OCR content at all on endcard).
6. When OCR-static is detected:
   a. Log the detection.
   b. Call a new helper function that grabs additional frames walking backward from the earliest
      tail frame timestamp (similar logic to the histogram backward walk, but triggered here).
   c. Run OCR on ONLY the new backward frames.
   d. Prepend the new OCR lines to ocr_text.
   e. Also prepend the new frames to the frames list (for gallery/artifact purposes).
7. Continue to LLM query with the enriched ocr_text.
```

### Key implementation notes

- **New helper in `video_io.py`**: Add a function `extend_frames_backward(url, before_timestamp, max_seconds=12, step_seconds=2)` that opens the video, grabs frames walking backward from the given timestamp. It should return the same frame dict format (`image`, `ocr_image`, `time`, `type`). Tag these frames as `"type": "ocr_dedup_ext"`.
- **Avoid double-extension**: If the histogram-based backward extension already fired (check if any frame has `"type": "backward_ext"`), skip this check entirely. The histogram approach already handled it — this refinement only catches what the histogram missed.
- **Text normalization**: Use a simple approach — `re.sub(r'[^a-z0-9\s]', '', text.lower()).strip()`. The goal is to detect identical _semantic_ content, not exact character matches. OCR often produces slightly different whitespace or punctuation across frames.
- **Similarity threshold**: Rather than requiring exact string equality, consider using simple set overlap. If the unique-word sets across all frames have a Jaccard similarity > 0.85, treat them as "effectively identical". This handles minor OCR jitter (e.g., "hulu.com" vs "hulu .com").
- **Safety cap**: Never grab more than 6 additional backward frames. Never walk back more than 12 seconds.
- **Do NOT re-run OCR on the original tail frames** — only OCR the newly grabbed backward frames and prepend to the existing text.

### Text parsing detail

The current `ocr_text` format (from pipeline.py line ~91) is:

```
[27.0s] Watch more at hulu.com
[28.5s] Watch more at hulu.com
[29.8s] Watch more at hulu.com
```

Parse each line with a regex like `r'^\[[\d.]+s\]\s*(.*)$'` to extract the text after the timestamp. Then normalize and compare.

### Function signatures

**In `video_io.py`** — add:

```python
def extend_frames_backward(
    url: str,
    before_timestamp: float,
    max_seconds: float = 12.0,
    step_seconds: float = 2.0,
) -> list[dict]:
```

**In `pipeline.py`** — no signature changes to `process_single_video`. The dedup logic is internal.

### Logging requirements

Use the existing `logger`. Log at these levels:

- `logger.debug(...)` — normalized OCR texts per frame (for debugging)
- `logger.info(...)` — when OCR dedup triggers: "ocr_dedup_triggered: all N tail frames produced identical text='...'"
- `logger.info(...)` — summary: "ocr_dedup_extended: grabbed M backward frames, new OCR text length=K chars"
- `logger.debug(...)` — when OCR texts are diverse (no dedup needed, normal case)

### Example scenarios

**Normal ad (no dedup)**:

- OCR texts: ["Nike Just Do It", "nike.com/shop", "Nike Air Max 2026"]
- Normalized unique set: 3 distinct values → no dedup. Zero extra cost.

**Animated endcard with static text (dedup fires)**:

- OCR texts: ["Watch more at hulu.com", "Watch more at hulu.com", "Watch more at hulu com"]
- Normalized unique set: effectively 1 value (Jaccard > 0.85) → dedup triggered
- Histogram did NOT catch this because the animation changed pixel values
- Backward extension grabs frames at [25.0s, 23.0s, 21.0s]
- OCR on those frames: ["Tide Pods — Clean Power", "Tide logo www.tide.com", "Family doing laundry"]
- Prepended to ocr_text → LLM now has both the useful brand text and the endcard text

**Already extended by histogram (skip)**:

- Frames list contains entries with `"type": "backward_ext"` → histogram already handled this
- Skip OCR dedup entirely.

## Files to modify

| File                             | Changes                                                             |
| -------------------------------- | ------------------------------------------------------------------- |
| `video_service/core/video_io.py` | Add `extend_frames_backward` helper function                        |
| `video_service/core/pipeline.py` | Add OCR dedup check in `process_single_video` after OCR, before LLM |

## Files to read for context

| File                              | Why                                                                                                                                            |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `video_service/core/video_io.py`  | Read the existing `extract_frames_for_pipeline` and histogram-based backward extension to understand the frame dict format and avoid conflicts |
| `video_service/core/ocr.py`       | Understand `ocr_manager.extract_text` signature and return type                                                                                |
| `video_service/core/pipeline.py`  | Understand the full flow of `process_single_video` — where OCR happens, where LLM is called, where frames are consumed                         |
| `video_service/workers/worker.py` | Verify that no worker-level changes are needed                                                                                                 |

## Constraints

- **Only modify `video_service/core/video_io.py` and `video_service/core/pipeline.py`**.
- **Do NOT change function signatures** of `process_single_video`, `run_pipeline_job`, or `extract_frames_for_pipeline`.
- **Do NOT re-run OCR on frames that were already OCR'd** — only OCR the new backward frames.
- **Do NOT add new dependencies** — `re`, `cv2`, and `os` are already available.
- **Type hints required** on the new `extend_frames_backward` function.
- **Never use `print()`** — structured logging only.
- **Graceful degradation**: if `extend_frames_backward` fails for any reason, catch the exception, log a warning, and continue with the original OCR text unchanged. This refinement must never break the pipeline.
- **Performance budget**: the OCR dedup check itself (text parsing + comparison) must be < 1ms. The backward extension (when triggered) is allowed the same budget as the histogram-based extension (~3–5 frame grabs).
