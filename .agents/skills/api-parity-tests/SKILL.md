---
name: api-parity-tests
description: Generates and runs parity tests to ensure the new API matches combined.py outputs.
---

# API Parity Tests Skill

## What to test
For each fixture:
- extracted frame timestamps match the selected scan strategy
- OCR output is present and stable
- final record fields exist (brand, category, confidence, reasoning)
- category mapping matches expected behavior

## Suggested helper
Run scripts/generate_parity_tests.py to scaffold pytest tests and golden files.
