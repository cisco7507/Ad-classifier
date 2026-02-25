# Optimization: Skip Duplicate OCR Frames in Pipeline

## Problem

In `pipeline.py` line ~92, OCR runs on **every** extracted frame sequentially:

```python
ocr_text = "\n".join([f"[{f['time']:.1f}s] {ocr_manager.extract_text(oe, f['ocr_image'], om)}" for f in frames])
```

With the fixed tail sampling (5 frames in 3 seconds) and possible backward extension, this may process 5–8 frames. But consecutive tail frames often show the **exact same brand card** held for 2+ seconds. Running OCR on 4 frames of the same static image costs 200–500ms each (800ms–2s total) for zero new information.

## Solution

After OCR-ing each frame, compare the text to the previous frame's text. If they're effectively identical, skip the duplicate and reuse the previous text. This eliminates redundant OCR calls without any loss of information.

## Implementation

### File: `video_service/core/pipeline.py`

Replace the single-line OCR comprehension (line ~92) with a loop that deduplicates:

```python
# Current (replace this):
ocr_text = "\n".join([f"[{f['time']:.1f}s] {ocr_manager.extract_text(oe, f['ocr_image'], om)}" for f in frames])

# New logic (pseudocode):
ocr_lines = []
prev_normalized = None
skipped_count = 0

for f in frames:
    raw_text = ocr_manager.extract_text(oe, f["ocr_image"], om)
    normalized = normalize(raw_text)  # lowercase, strip punct/whitespace

    if prev_normalized is not None and similarity(normalized, prev_normalized) > 0.85:
        skipped_count += 1
        # Still log the timestamp but mark as duplicate
        logger.debug("ocr_dedup_skip: frame at %.1fs identical to previous", f["time"])
        continue

    ocr_lines.append(f"[{f['time']:.1f}s] {raw_text}")
    prev_normalized = normalized

ocr_text = "\n".join(ocr_lines)
logger.debug("ocr_dedup: processed=%d skipped=%d total_frames=%d", len(ocr_lines), skipped_count, len(frames))
```

### Text normalization and similarity

Use a simple approach:

```python
def _normalize_ocr(text: str) -> str:
    return re.sub(r'[^a-z0-9\s]', '', (text or '').lower()).strip()

def _ocr_texts_similar(a: str, b: str, threshold: float = 0.85) -> bool:
    if not a and not b:
        return True
    if not a or not b:
        return False
    words_a, words_b = set(a.split()), set(b.split())
    if not words_a and not words_b:
        return True
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) >= threshold  # Jaccard similarity
```

Place these as module-level helper functions in `pipeline.py` (or in a shared utils file if preferred).

### Key implementation notes

- **Threshold of 0.85 Jaccard**: catches OCR jitter (minor whitespace/punctuation differences between frames of the same card) while preserving genuinely different text transitions.
- **Always OCR the first frame** — never skip it (there's nothing to compare against).
- **Always OCR the last frame** — even if it appears identical to the previous, the last frame is what gets sent as `tail_image` to the LLM on line ~95. We want its OCR regardless.
- **The `ocr_text` variable format** must remain unchanged — newline-delimited lines with `[timestamp] text`. The LLM prompt and downstream code depend on this format.
- **Make the similarity threshold configurable** via `os.environ.get("OCR_DEDUP_THRESHOLD", "0.85")`.
- **Log at DEBUG level** which frames were skipped, and a summary at INFO of total vs skipped.

### What NOT to change

- Do NOT change `extract_text` in `ocr.py`.
- Do NOT change `video_io.py`.
- Do NOT change `worker.py`.
- The LLM call on line ~95 must still receive `frames[-1]["image"]` — this is unrelated to OCR dedup.

## Constraints

- **Only modify `video_service/core/pipeline.py`**.
- **No new dependencies.**
- **Type hints** on helper functions.
- **Structured logging only** — never `print()`.
- **The optimization must be transparent** — downstream code sees the same `ocr_text` format, just with fewer (non-redundant) lines.
