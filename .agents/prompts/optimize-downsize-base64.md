# Optimization: Downsize Base64 Image Sent to LLM

## Problem

In `llm.py`, `_pil_to_base64` (lines 59–63) encodes the tail image at **full resolution**:

```python
def _pil_to_base64(self, pil_image):
    if not pil_image: return None
    buffered = io.BytesIO()
    pil_image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")
```

For a 1920×1080 frame, this produces a ~100–300KB JPEG, which base64-encodes to ~130–400KB of text. This payload is sent to Ollama/LM Studio in the JSON request body. Larger images mean:

- More memory consumed by the LLM for image token encoding
- Slightly longer inference time (image tokens scale with resolution)
- Larger HTTP request payload (network overhead for LM Studio remote setups)

Most vision-language models (LLaVA, Qwen-VL, etc.) internally resize images to 336–768px anyway. Sending 1920px is wasted bandwidth.

## Solution

Resize the PIL image to a maximum dimension of **768px** (preserving aspect ratio) before JPEG encoding. This matches the input resolution of most VLMs and reduces payload size by ~70%.

### Implementation

**File: `video_service/core/llm.py`**

Update `_pil_to_base64`:

```python
def _pil_to_base64(self, pil_image, max_dimension=768):
    if not pil_image: return None

    # Downsize if larger than max_dimension on either axis
    w, h = pil_image.size
    if max(w, h) > max_dimension:
        scale = max_dimension / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        pil_image = pil_image.resize((new_w, new_h), Image.LANCZOS)

    buffered = io.BytesIO()
    pil_image.save(buffered, format="JPEG", quality=85)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")
```

### Key implementation notes

- **`max_dimension=768`**: Configurable via parameter. 768px is the sweet spot — matches SigLIP's 384px (2×) and most VLM internal resolutions.
- **`Image.LANCZOS`**: High-quality downscaling filter. Use `Image.Resampling.LANCZOS` if on Pillow ≥ 9.1.
- **`quality=85`**: Slightly compressed JPEG (default is 75). Good visual quality, ~40% smaller file than quality=95.
- **Only resize if necessary**: Images already ≤768px pass through unchanged.
- **Aspect ratio preserved**: Scale factor applied uniformly to both dimensions.
- **`Image` is already imported** in this file (via `from PIL import Image` — check imports; if not present, it's available from `io` usage).

### Check: is PIL Image imported?

Looking at the current imports in `llm.py`:

```python
import io
import base64
```

PIL's `Image` is NOT currently imported in `llm.py`. You'll need to add:

```python
from PIL import Image
```

However, `_pil_to_base64` already receives a PIL Image object and calls `.save()` on it, so PIL is an implicit dependency. The `.resize()` call requires `Image.LANCZOS` from PIL. Add the import.

### Payload size comparison (1920×1080 input)

| Metric           | Before    | After (768px) |
| ---------------- | --------- | ------------- |
| Image dimensions | 1920×1080 | 768×432       |
| JPEG size        | ~150KB    | ~35KB         |
| Base64 size      | ~200KB    | ~47KB         |
| Reduction        | —         | **~75%**      |

## Files to modify

| File                        | Changes                                                                        |
| --------------------------- | ------------------------------------------------------------------------------ |
| `video_service/core/llm.py` | Add `from PIL import Image`; update `_pil_to_base64` to resize before encoding |

## Constraints

- **Only modify `video_service/core/llm.py`**.
- **Do NOT change `_pil_to_base64`'s external interface** — callers still pass a PIL Image, get back a base64 string.
- **Do NOT resize to a fixed size** — preserve aspect ratio.
- **Do NOT change image format** — keep JPEG.
- **Quality must remain visually clear** — the LLM needs to read text/logos in the image. Quality=85 is the floor; do not go lower.
- **Never use `print()`**.
