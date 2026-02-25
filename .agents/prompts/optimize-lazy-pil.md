# Optimization: Lazy PIL Image Conversion

## Problem

In `video_io.py`, every frame extraction creates a PIL image immediately (line ~182):

```python
frames.append({
    "image": Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)),  # ← eager PIL conversion
    "ocr_image": fr,
    "time": t/fps,
    "type": frame_type,
})
```

The `"image"` field (PIL Image) is only consumed by:

1. **Vision scoring** (SigLIP) — if enabled
2. **LLM multimodal** — only the _last_ frame's image is sent (as base64 JPEG)

If Vision is disabled and the LLM is text-only, PIL conversion is wasted work. Even when Vision is enabled, the backward extension frames (tagged `"backward_ext"`) are primarily for OCR — their PIL images are rarely used by Vision.

The conversion cost per frame is ~5–30ms depending on resolution (1080p → ~15ms). With 5–8 frames, that's 75–240ms of potentially wasted work.

## Solution

Defer PIL image creation until the consumer actually needs it. Replace the eager `Image.fromarray(...)` with a lazy accessor.

### Approach: Store raw BGR frame, convert on access

Instead of storing `"image": Image.fromarray(...)`, store a reference to the raw frame and convert lazily:

```python
frames.append({
    "image": None,        # deferred
    "ocr_image": fr,      # raw BGR (already stored)
    "time": t/fps,
    "type": frame_type,
    "_pil_cache": None,    # lazy cache
})
```

Then add a helper function that consumers call:

```python
def get_pil_image(frame: dict) -> Image.Image:
    if frame.get("_pil_cache") is not None:
        return frame["_pil_cache"]
    pil = Image.fromarray(cv2.cvtColor(frame["ocr_image"], cv2.COLOR_BGR2RGB))
    frame["_pil_cache"] = pil
    frame["image"] = pil  # backfill for any code reading "image" directly
    return pil
```

### Files to modify

| File                             | Changes                                                                                         |
| -------------------------------- | ----------------------------------------------------------------------------------------------- |
| `video_service/core/video_io.py` | Stop creating PIL images in frame dicts; add `get_pil_image()` helper                           |
| `video_service/core/pipeline.py` | Use `get_pil_image()` where `f["image"]` is currently accessed (vision scoring, LLM tail image) |
| `video_service/core/agent.py`    | Use `get_pil_image()` where `f["image"]` is currently accessed                                  |

### Key implementation notes

- **The `"image"` key must still exist** in the frame dict (set to `None`) for backward compatibility — some code may check `if f["image"]`.
- **Cache the result** in `_pil_cache` so repeated access doesn't re-convert.
- **Also backfill `frame["image"]`** on first access so that any code reading the key directly gets the cached PIL image.
- **The conversion itself is unchanged** — `Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))`. Same quality, same output.
- **`get_pil_image` should live in `video_io.py`** and be imported by consumers.

### Consumer call sites to update

**In `pipeline.py`:**

- Line ~67: `pil_images = [f["image"] for f in frames]` → `pil_images = [get_pil_image(f) for f in frames]`
- Line ~95: `frames[-1]["image"]` → `get_pil_image(frames[-1])`

**In `agent.py`:**

- Line ~93: `pil_images = [f["image"] for f in frames_data]` → `pil_images = [get_pil_image(f) for f in frames_data]`

## Constraints

- **Only modify `video_service/core/video_io.py`, `pipeline.py`, and `agent.py`**.
- **Do NOT change OCR code** — OCR already uses `f["ocr_image"]` (raw BGR), not `f["image"]`.
- **Do NOT change worker.py**.
- **Frame dict format must remain compatible** — the `"image"` key must still be present.
- **Type hints** on `get_pil_image`.
- **Never use `print()`**.
