# Optimization: Parallelize OCR and Vision Scoring

## Problem

In `pipeline.py` `process_single_video`, Vision scoring (SigLIP) and OCR run **sequentially**:

```
lines 57-88:  Vision scoring (SigLIP) → wait for completion
lines 90-92:  OCR extraction → wait for completion
lines 94-95:  LLM query (depends on both Vision and OCR output)
```

Vision operates on PIL images. OCR operates on raw BGR frames (`ocr_image`). They share no data dependencies and can run concurrently. Currently, the slower of the two blocks the overall pipeline unnecessarily.

Typical timings:

- Vision (SigLIP on 5 frames): 0.5–2s
- OCR (EasyOCR on 5 frames): 1–3s
- Sequential total: 1.5–5s
- **Parallel total: max(Vision, OCR) = 1–3s** → saves 0.5–2s per video

## Solution

Run Vision and OCR concurrently using `concurrent.futures.ThreadPoolExecutor`. Both are I/O-or-GPU-bound (not CPU-bound), so threading is appropriate. Collect results from both before proceeding to the LLM call.

## Implementation

### File: `video_service/core/pipeline.py`

Currently the flow in `process_single_video` is:

```python
# 1. Vision scoring (lines 57-88)
sorted_vision = {}
if enable_vision:
    # ... SigLIP computation ...

# 2. OCR (lines 90-92)
ocr_text = "\n".join([...])

# 3. LLM (line 95)
res = llm_engine.query_pipeline(p, m, ocr_text, ...)
```

Refactor to:

```python
# Define the two independent tasks
def _do_vision():
    # Move the entire vision block (lines 57-88) into this function
    # Return sorted_vision dict
    ...

def _do_ocr():
    # Move the OCR line (line 92) into this function
    # Return ocr_text string
    ...

# Run them concurrently
sorted_vision = {}
ocr_text = ""

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    vision_future = pool.submit(_do_vision) if enable_vision else None
    ocr_future = pool.submit(_do_ocr)

    ocr_text = ocr_future.result()
    sorted_vision = vision_future.result() if vision_future else {}

# 3. LLM (depends on both)
res = llm_engine.query_pipeline(p, m, ocr_text, ...)
```

### Key implementation notes

- **Define `_do_vision` and `_do_ocr` as nested functions** inside `process_single_video` so they have access to `frames`, `oe`, `om`, `enable_vision`, `stage_callback`, etc. via closure. This avoids changing function signatures.
- **Stage callbacks**: Both tasks call `stage_callback`. This is safe — the callback just does a DB update with a WHERE clause on job_id. Concurrent calls won't conflict.
- **Error handling**: If either task raises an exception, `future.result()` will re-raise it. Wrap each in try/except inside the task function, matching the current error handling patterns.
- **`concurrent.futures` is already imported** in `pipeline.py` (line 5).
- **Thread safety of OCR**: If using Florence-2, `ocr_manager` already has a `florence_infer_lock`. If using EasyOCR, the reader is thread-safe for `readtext()` calls on different images. No additional locking needed.
- **Thread safety of SigLIP**: The vision computation uses `torch.no_grad()` and only reads model weights. Safe for concurrent execution with OCR threads.
- **If Vision is disabled**: Don't submit the vision future at all — just run OCR directly (no thread pool overhead needed for a single task). In this case, skip the `ThreadPoolExecutor` entirely:

```python
if enable_vision:
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        vision_future = pool.submit(_do_vision)
        ocr_future = pool.submit(_do_ocr)
        ocr_text = ocr_future.result()
        sorted_vision = vision_future.result()
else:
    ocr_text = _do_ocr()
    sorted_vision = {}
```

### Logging

- Log the start and end of each parallel task at DEBUG level.
- Log the total wall-clock time for the parallel section at INFO level:

```python
t0 = time.time()
# ... parallel execution ...
logger.info("parallel_ocr_vision: completed in %.2fs", time.time() - t0)
```

## Files to modify

| File                             | Changes                                                             |
| -------------------------------- | ------------------------------------------------------------------- |
| `video_service/core/pipeline.py` | Refactor vision + OCR into parallel tasks in `process_single_video` |

## Constraints

- **Only modify `video_service/core/pipeline.py`**.
- **Do NOT change `ocr.py`** — the OCR manager's thread safety is already handled internally.
- **Do NOT change `categories.py`** — SigLIP read-only inference is inherently thread-safe.
- **Do NOT change the function signature** of `process_single_video` or `run_pipeline_job`.
- **The LLM call must still wait for both Vision and OCR** — it depends on both outputs.
- **Stage callbacks must still fire** in both tasks for progress reporting.
- **Type hints and structured logging** — follow existing patterns.
- **Never use `print()`**.
