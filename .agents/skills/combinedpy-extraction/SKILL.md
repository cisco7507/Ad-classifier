---
name: combinedpy-extraction
description: Safely extracts and ports combined.py core logic into testable modules while preserving behavior.
---

# combined.py Extraction Skill

## When to use
Whenever you touch classification logic or refactor combined.py.

## Rules
1) Do not change behavior without a parity test update.
2) Extract into modules by responsibility:
   - video_io (URL/local ingestion, frame extraction strategies)
   - ocr (EasyOCR / Florence adapter)
   - llm (providers + prompt orchestration)
   - categories (CategoryMapper + embeddings + plots)
   - pipeline (process_single_video equivalent)
   - agent (AdClassifierAgent loop + event streaming)

## Suggested automation
Run scripts/extract_core_modules.py to scaffold the module layout.
