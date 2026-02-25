# Cleanup: Remove Stale print() in llm.py

## Problem

`video_service/core/llm.py` line 101 contains a leftover debug `print()`:

```python
res = call_model(sys_msg, usr_msg, b64_img if force_multimodal else None)
print(f'RES VALUE IS: {res}')
```

This violates the project rule: "never `print()` in server code". It writes unstructured output to stdout on every pipeline LLM call, which:

- Pollutes worker process logs
- Is not correlated with job_id or any structured context
- Cannot be filtered or leveled like proper log messages

## Fix

Replace with a structured log call:

```python
logger.debug("llm_pipeline_initial_result: %s", res)
```

`logger` is already imported in this file (line 13: `from video_service.core.utils import logger`).

## File to modify

| File                        | Changes                                                                      |
| --------------------------- | ---------------------------------------------------------------------------- |
| `video_service/core/llm.py` | Replace `print(f'RES VALUE IS: {res}')` on line 101 with `logger.debug(...)` |

## Constraints

- **Single line change.**
- **Only modify `video_service/core/llm.py`**.
