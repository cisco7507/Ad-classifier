# Bugfix: Filter Out Prose Fragments from Reasoning Signal Pills

## Problem

The LLM Reasoning card extracts quoted terms (text between single quotes `'...'`) and renders them as colored signal pills. However, the regex `/'([^']+)'/g` also captures **prose fragments** when the LLM uses possessive apostrophes (e.g., `Boeing's`) or nested quotes. These fragments appear as oversized, meaningless pills:

**Broken pills currently appearing:**

- `"— all are factual and consistent with Boeing's commercial aviation history. Despite OCR noise (e.g.,"`
- `"likely meant"`
- `"), the context clearly points to Boeing as the brand. The category"`

**Valid pills that should remain:**

- `Boeing 717s`
- `Midwest Airlines`
- `AirTran Airways`
- `Boeing`
- `thebrick.com`
- `PROUDLY CANADIAN SINCE 1971`

## Root Cause

The regex `/'([^']+)'/g` matches text between ANY two single quote characters. When the LLM writes `Boeing's Long Beach facility' — all are factual`, the regex sees the apostrophe in `Boeing's` as an opening quote and the next `'` as a closing quote, capturing everything in between as a "term".

## Fix

Add a validation filter after extracting quoted terms. Filter out any term that is clearly a prose fragment rather than a brand name, slogan, URL, or OCR artifact.

### Validation function

```typescript
function isValidSignalPill(text: string): boolean {
  const trimmed = text.trim();

  // Too long — brand names and slogans are almost always under 50 chars
  if (trimmed.length > 50) return false;

  // Too short — single characters aren't useful
  if (trimmed.length < 2) return false;

  // Starts with punctuation — it's a sentence fragment
  if (/^[—\-,;:)\.\!\?]/.test(trimmed)) return false;

  // Ends with punctuation that suggests a sentence fragment
  if (/[,;:\(]$/.test(trimmed)) return false;

  // Contains too many words — slogans cap around 8 words, prose goes longer
  const wordCount = trimmed.split(/\s+/).length;
  if (wordCount > 10) return false;

  return true;
}
```

### Where to apply

In the `quotedTerms` `useMemo` (or wherever the extracted terms array is built), add `.filter(isValidSignalPill)` BEFORE the type-categorization step:

```typescript
const quotedTerms = useMemo(() => {
  const reasoning = firstRow?.Reasoning || "";
  const matches = reasoning.match(/'([^']+)'/g);
  if (!matches) return [];
  const unique = [...new Set(matches.map((m) => m.slice(1, -1)))];

  // NEW: Filter out prose fragments
  const valid = unique.filter(isValidSignalPill);

  return valid.map((term) => {
    // ... existing type categorization (brand/url/evidence) ...
  });
}, [firstRow?.Reasoning, firstRow?.Brand]);
```

### Also apply to inline highlighting

The same filter should apply to the inline text highlighting logic. If a term was filtered out of the pills, it should NOT be highlighted in the body text either — otherwise you'd have highlighted prose fragments in the paragraph with no matching pill above.

## File to modify

`frontend/src/pages/JobDetail.tsx` — add the filter function and apply it to the existing pill extraction logic.

## Constraints

- **Only modify `frontend/src/pages/JobDetail.tsx`**.
- **Do NOT change the regex itself** — the `/'([^']+)'/g` pattern is fine for extraction; the filtering happens after.
- **Do NOT remove the "Show less" / "+N more" truncation** — it should still work, just with fewer (valid) pills.
- **Keep the `isValidSignalPill` function simple** — no NLP, no external dependencies. Pure string heuristics.
- **Test mentally against these examples:**
  - `"Boeing 717s"` → ✅ valid (12 chars, 2 words)
  - `"PROUDLY CANADIAN SINCE 1971"` → ✅ valid (28 chars, 4 words)
  - `"thebrick.com"` → ✅ valid (12 chars, 1 word)
  - `"— all are factual and consistent with Boeing's commercial aviation history."` → ❌ filtered (>50 chars, starts with `—`)
  - `"likely meant"` → ✅ valid (12 chars, but this is borderline — acceptable to keep as it's short)
  - `"), the context clearly points to Boeing as the brand. The category"` → ❌ filtered (starts with `)`, >50 chars)
