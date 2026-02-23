---
description: 
---

Goal: ensure API outputs match combined.py outputs.

Steps:
1) Pick 3 fixtures:
   - URL video
   - local mp4
   - longer video where tail-only vs full matters
2) Run combined.py to capture expected outputs:
   - OCR text output
   - final classification record fields
3) Run service API and compare:
   - frame timestamps strategy matches
   - OCR behavior matches for chosen engine
   - category mapping output matches expected behavior
4) Record acceptable tolerances (if any) and justify.

Exit criteria:
- Parity tests pass in CI
