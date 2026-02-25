# Optimization: Conditional LLM Validation Call

## Problem

In `llm.py` `query_pipeline` (lines ~100–114), when `enable_search=True`, up to **3 sequential LLM calls** are made per video:

1. **Initial classification** (line 100) — always runs.
2. **Agentic recovery** (lines 104–109) — runs when brand is "Unknown"; does a web search, then calls the LLM again. This is valuable and should be kept.
3. **Validation** (lines 111–114) — runs on **every successful classification**; does another web search and an LLM call just to "correct" the brand name.

The validation call (step 3) fires on 100% of successful runs, adding 2–8 seconds per video. For high-confidence, clean classifications (e.g., OCR clearly says "Nike" and the LLM returns `{"brand": "Nike", "confidence": 0.95}`), this validation is pure waste.

## Current Code (lines 111–114)

```python
if "category" in res and enable_search and brand.lower() not in ["unknown", "none", "n/a", ""]:
    if val_snippets := search_manager.search(f"{brand} official brand company"):
        val_res = call_model(sys_msg + "\nVALIDATION MODE", f"Brand: {brand}\nWeb: {val_snippets}\nCorrect brand name. Keep category {res.get('category')}.")
        if "category" in val_res: return val_res
```

This always fires when a brand was found and search is enabled. There is no confidence gate.

## Solution

Gate the validation call on confidence. Only validate when the LLM's own confidence is low, indicating uncertainty that web validation might resolve.

### Logic

```python
confidence = res.get("confidence", 0.0) if isinstance(res, dict) else 0.0
needs_validation = confidence < validation_threshold

if "category" in res and enable_search and brand.lower() not in ["unknown", "none", "n/a", ""] and needs_validation:
    # existing validation logic...
```

### Implementation details

- **Default threshold**: `0.7` — classifications with confidence ≥ 0.7 skip validation. This is configurable via `os.environ.get("LLM_VALIDATION_THRESHOLD", "0.7")`.
- **Parse the threshold once** at the top of `query_pipeline`, not on every call.
- **Log the decision** at DEBUG level:
  - `"llm_validation_skipped: confidence=%.2f >= threshold=%.2f"` when skipping
  - `"llm_validation_triggered: confidence=%.2f < threshold=%.2f"` when running
- **If `confidence` is missing or 0.0**, always validate (treat missing confidence as uncertain).
- **If `confidence` is a string** (some models return `"0.9"` as a string), parse it to float with a try/except fallback to 0.0.

### Additional cleanup

There is a stale `print()` on line 101:

```python
print(f'RES VALUE IS: {res}')
```

This violates the project rules ("never `print()` in server code"). Replace with:

```python
logger.debug("llm_pipeline_initial_result: %s", res)
```

## Files to modify

| File                        | Changes                                                                          |
| --------------------------- | -------------------------------------------------------------------------------- |
| `video_service/core/llm.py` | Add confidence gate to validation block; replace `print()` with `logger.debug()` |

## Constraints

- **Only modify `video_service/core/llm.py`**.
- **Do NOT change the agentic recovery logic** (lines 104–109) — that only fires on "Unknown" brand and is valuable.
- **Do NOT change the `query_agent` method** — agent mode is unaffected.
- **Do NOT change the function signature** of `query_pipeline`.
- **Do NOT remove the validation capability** — just gate it on confidence.
- **Preserve backward compatibility**: with threshold at 0.0, behavior is identical to current (always validate).
- **Structured logging only** — never `print()`.
