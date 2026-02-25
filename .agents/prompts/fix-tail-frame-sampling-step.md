# Bugfix: Tail Mode Frame Sampling Produces Only 1 Frame

## Critical Bug

In "Tail Only" scan mode, the frame sampling step size is calculated relative to the **full video length** (`total / 6`), but then applied to a **3-second tail window**. This causes the loop to overshoot the window and produce only **1 frame** for any video under ~90 seconds. This means:

1. The LLM receives OCR from a single frame — if that frame lacks the brand, classification fails.
2. The histogram-based static endcard detection (implemented in `_maybe_extend_tail_frames`) requires ≥3 frames and **never triggers**.

### Proof

For a 30-second ad at 30fps:

```
total = 900 frames
fps = 30
start = int(max(0, (900/30) - 3) * 30) = int(27 * 30) = 810
step  = max(1, int(900 / 6)) = 150

range(810, 900, 150) → yields [810] → ONE frame at 27.0s
```

Next value would be 810 + 150 = 960, which exceeds `total` (900), so the loop ends.

### Impact across all standard ad lengths

| Duration | start (frame) | step | Frames | Histogram check works? |
| -------- | ------------- | ---- | ------ | ---------------------- |
| 6s       | 90            | 30   | 3      | ✅ (barely)            |
| 15s      | 360           | 75   | 2      | ❌ needs ≥3            |
| 30s      | 810           | 150  | 1      | ❌                     |
| 60s      | 1710          | 300  | 1      | ❌                     |
| 90s      | 2610          | 450  | 1      | ❌                     |
| 120s     | 3510          | 600  | 1      | ❌                     |

## Root Cause

Line in `extract_frames_for_pipeline` in `video_service/core/video_io.py`:

```python
step = max(1, int(total / 6))
```

This formula makes sense for "Full Video" mode (6 evenly-spaced samples across the whole timeline) but is wrong for tail mode. The step should be proportional to the **tail window size** (3 seconds), not the full video length.

## Fix

Replace the tail-mode step calculation so it produces a **configurable target number of frames** within the 3-second tail window. The default should be **5 frames**, which gives approximately one frame every 0.6 seconds — dense enough for the histogram check and OCR coverage, but still very lightweight.

### Target behavior after fix

For a 30-second ad at 30fps:

```
tail_window_seconds = 3
target_tail_frames = 5
start = int((30 - 3) * 30) = 810
step  = max(1, int(3 * 30 / 5)) = max(1, 18) = 18

range(810, 900, 18) → [810, 828, 846, 864, 882] → 5 frames
```

Timestamps: [27.0s, 27.6s, 28.2s, 28.8s, 29.4s]

### Expected results after fix

| Duration | Frames (before) | Frames (after) | Histogram works? |
| -------- | --------------- | -------------- | ---------------- |
| 6s       | 3               | 5              | ✅               |
| 15s      | 2               | 5              | ✅               |
| 30s      | 1               | 5              | ✅               |
| 60s      | 1               | 5              | ✅               |
| 120s     | 1               | 5              | ✅               |

Consistent 5 frames regardless of video length — the tail window is always 3 seconds.

## Implementation

### File: `video_service/core/video_io.py`

In `extract_frames_for_pipeline`, change only the `else` (tail mode) branch. Currently:

```python
else:
    start = int(max(0, (total / fps) - 3) * fps)
    step = max(1, int(total / 6))          # ← BUG: step based on full video
    frame_type = "tail"
```

Change to:

```python
else:
    tail_window_seconds = 3
    target_tail_frames = _parse_int_env("TAIL_TARGET_FRAMES", 5)
    start = int(max(0, (total / fps) - tail_window_seconds) * fps)
    tail_window_frames = total - start
    step = max(1, int(tail_window_frames / max(1, target_tail_frames)))
    frame_type = "tail"
```

`_parse_int_env` already exists in this file (used by the histogram feature). The `TAIL_TARGET_FRAMES` env var allows tuning without code changes. Default of 5 balances coverage with speed.

### Logging

Add a debug log line after computing the step so the frame count is observable:

```python
logger.debug(
    "tail_sampling: start_frame=%d step=%d expected_frames=%d tail_window=%.1fs",
    start, step, len(range(start, total, step)), tail_window_seconds,
)
```

## Constraints

- **Only modify `video_service/core/video_io.py`** — no changes to any other file.
- **Only modify the tail-mode branch** in `extract_frames_for_pipeline`. Do NOT change the Full Video branch.
- **Do NOT change the function signature** of `extract_frames_for_pipeline`.
- **Do NOT change `_maybe_extend_tail_frames`** — the histogram logic is correct; it just wasn't receiving enough frames to work with.
- **Do NOT change `extract_frames_for_agent`** — agent mode is unaffected.
- The `_parse_int_env` helper already exists in this file — use it.
- **Type hints and structured logging** — follow the patterns already in the file.
- **Never use `print()`**.

## Verification

After applying this fix, verify with a quick mental trace:

1. A 30-second video should produce ~5 tail frames (not 1).
2. `_maybe_extend_tail_frames` should now actually receive ≥3 frames and be able to check for static endcards.
3. Full Video mode is unchanged (start=0, step=fps\*2).
4. Very short videos (e.g., 3 seconds) should still work — `start` would be 0, and `step` would be `max(1, int(total / 5))`.
