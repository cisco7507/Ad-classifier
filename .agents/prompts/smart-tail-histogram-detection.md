# Feature: Smart Tail Sampling via Histogram-Based Static Frame Detection

## Problem

In "Tail Only" scan mode, `extract_frames_for_pipeline` in `video_service/core/video_io.py` grabs ~2–3 frames from the last 3 seconds of a video. This works well when the last seconds contain a brand card (logo, slogan, URL). However, some ads end with a **static endcard** — a broadcaster bumper, legal disclaimer, network logo, or generic "watch more" screen — that does NOT contain the advertiser's brand. The real brand card appeared 5–10 seconds earlier and is never captured. The LLM then receives misleading OCR and misclassifies the ad.

## Solution: Static Frame Detection + Backward Extension

After grabbing the normal tail frames, compare them to each other using `cv2.compareHist`. If they are all nearly identical (static endcard), automatically walk backward in time to find frames with different visual content. This adds almost zero cost for normal ads (histogram comparison is sub-millisecond) and only pays extra frame-grab cost when the edge case is actually detected.

## Implementation Details

### Where to implement

All changes go in **`video_service/core/video_io.py`**, specifically inside or after `extract_frames_for_pipeline`. No other files need modification — the pipeline, OCR, and LLM layers work on whatever frames this function returns.

### Algorithm

```
1. Extract tail frames as currently implemented (last ~3 seconds, step = total/6).
2. If fewer than 2 frames were extracted, return immediately (nothing to compare).
3. Convert each frame to an HSV histogram (cv2.calcHist on the H and S channels, normalized).
4. Compare all consecutive frame pairs using cv2.compareHist with cv2.HISTCMP_CORREL.
5. If ALL pair correlations exceed a threshold (e.g., 0.97), the tail is a static endcard.
6. When static endcard detected:
   a. Walk backward from the current start position in 2-second hops.
   b. Grab one frame per hop.
   c. Compute its histogram and compare to the static endcard histogram.
   d. Stop when:
      - The correlation drops below the threshold (found a different scene), OR
      - You've walked back 12 seconds total (safety cap to avoid scanning the whole video).
   e. Insert any "different" frames at the FRONT of the frames list.
7. Log what happened (static detection triggered, how far back it walked, how many extra frames).
8. Return the (possibly extended) frames list as normal.
```

### Key implementation notes

- **Histogram method**: Use HSV color space (not BGR) for robustness against minor brightness variations. Use 2D histogram on H (50 bins) and S (60 bins) channels. Normalize with `cv2.normalize`.
- **Comparison method**: `cv2.HISTCMP_CORREL` returns 1.0 for identical images, ~0 for unrelated. Threshold of **0.97** is a good starting point — high enough to avoid false positives on intentional visual changes, low enough to catch endcards that may have subtle animation.
- **Make the threshold configurable** via `os.environ.get("TAIL_STATIC_THRESHOLD", "0.97")` so it can be tuned without code changes.
- **Make the max backward walk configurable** via `os.environ.get("TAIL_MAX_BACKWARD_SECONDS", "12")`.
- **The backward walk should reuse the same `cv2.VideoCapture` object** that's already open — don't re-open the video. The capture is returned alongside frames, so this requires a small restructure: do the detection before `return frames, cap` while `cap` is still open.
- **Frame type tagging**: tag backward-extension frames as `"type": "backward_ext"` so downstream code can distinguish them if needed.
- **Performance**: the histogram computation and comparison for 2–3 frames takes <1ms total. The backward walk, when triggered, adds ~3–5 frame seeks and reads — comparable cost to the original tail extraction.

### Function signature

The function signature does NOT change. The smart tail logic is internal to `extract_frames_for_pipeline`:

```python
def extract_frames_for_pipeline(url: str, scan_mode: str = "Tail Only") -> tuple[list[dict], cv2.VideoCapture]:
```

The backward extension should **only** run when `scan_mode` is tail-based (not "Full Video"), since Full Video already covers the entire timeline.

### Logging requirements

Use the existing `logger` from `video_service.core.utils`. Log at these levels:

- `logger.debug(...)` — histogram scores for each frame pair (for tuning)
- `logger.info(...)` — when static endcard is detected and backward walk begins
- `logger.info(...)` — summary: "backward_walk: extended N seconds, added M frames"
- `logger.debug(...)` — when tail frames are NOT static (normal case, no extension needed)

Never use `print()`.

### Example scenarios

**Normal ad (no extension)**:

- Tail frames captured at [27.0s, 28.5s, 29.8s]
- Histogram correlations: [0.62, 0.71] → below threshold
- Result: return the 3 frames as-is. Zero extra cost.

**Static endcard detected**:

- Tail frames captured at [27.0s, 28.5s, 29.8s]
- Histogram correlations: [0.99, 0.99] → all above 0.97 → static endcard!
- Backward walk: grab frames at [25.0s, 23.0s, 21.0s, 19.0s]
- Correlations vs endcard: [0.99, 0.98, 0.41, —]
- Frame at 21.0s is different → stop walking
- Return frames: [21.0s, 23.0s, 25.0s, 27.0s, 28.5s, 29.8s] (6 frames total, 3 extra)

## Files to read for context

| File                             | Why                                                                                                                                    |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `video_service/core/video_io.py` | **This is the only file you modify.** Read the current `extract_frames_for_pipeline` implementation.                                   |
| `video_service/core/pipeline.py` | Understand how `extract_frames_for_pipeline` is called and how frames are consumed downstream. Verify no signature changes are needed. |
| `video_service/core/ocr.py`      | Understand the frame dict structure (`"image"`, `"ocr_image"`, `"time"`, `"type"`) that downstream OCR expects.                        |

## Constraints

- **Only modify `video_service/core/video_io.py`**. No changes to pipeline.py, ocr.py, worker.py, or any other file.
- **Do NOT change the function signature** of `extract_frames_for_pipeline`.
- **Do NOT change the "Full Video" scan mode path** — backward extension only applies to tail mode.
- **Do NOT add new dependencies** — `cv2` (OpenCV) is already available.
- **Type hints required** on any new helper functions.
- **Never use `print()`** — structured logging only.
- **The backward extension is a best-effort optimization** — if it fails for any reason (e.g., seek error), catch the exception, log a warning, and return the original tail frames unchanged.
