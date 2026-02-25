# UI Fix: Consolidate Redundant Classification Sections

## Problem

When a job is completed, the Job Detail page shows the same classification data **three times**:

1. **Header section** — "Current Stage: completed / Stage Detail: result persisted" (redundant with COMPLETED badge)
2. **Summary Verdict Bar** — "The Brick → Home Improvement (ID: 5192) | 0.99 | Embed. (0.65) | 5 frames"
3. **Final Classification cards** — Three separate cards for Category, Brand, Confidence (repeats everything in the summary bar)

Additionally:

- Card text is not centered
- The "and" word appears as a signal pill in the reasoning card (pill filter gap)

## Fix

### 1. Hide the Stage Info Boxes for Completed/Failed Jobs

The "Current Stage" and "Stage Detail" boxes (inside the header card) are useful during processing but redundant once the job is done — the green `COMPLETED` badge already communicates the status.

**In the header card** (the section containing "Current Stage" / "Stage Detail" grid, approximately within lines 196–205 of `JobDetail.tsx`):

Wrap the stage info grid with a condition:

```tsx
{
  job.status !== "completed" && job.status !== "failed" && (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
      <div className="bg-slate-950/70 border border-slate-800 rounded p-3">
        <div className="uppercase tracking-wider text-slate-500 mb-1">
          Current Stage
        </div>
        <div className="text-slate-200 font-mono">{job.stage || "unknown"}</div>
      </div>
      <div className="bg-slate-950/70 border border-slate-800 rounded p-3">
        <div className="uppercase tracking-wider text-slate-500 mb-1">
          Stage Detail
        </div>
        <div className="text-slate-300">{job.stage_detail || "—"}</div>
      </div>
    </div>
  );
}
```

This shows the stage info only during `queued` or `processing`.

### 2. Hide the Final Classification Cards When Summary Bar Is Visible

The Summary Verdict Bar already shows Brand, Category, ID, Confidence, Match, and Frames. The three-card grid repeats all of this. **For completed jobs, remove the card grid entirely.**

Find the "Final Classification" section (the `<h2>` with "Final Classification" and the three-card grid). Wrap the entire section so it only renders when the summary bar is NOT visible — or simply remove it entirely since the summary bar supersedes it:

```tsx
{
  /* OLD: Three classification cards — REMOVE or hide for completed jobs */
}
{
  /* The Summary Verdict Bar above already shows all this data */
}
```

**Option A (Recommended — Remove entirely):** Delete the entire "Final Classification" section (the `<h2>` + the three-card `grid`). The Summary Verdict Bar is the classification result.

**Option B (Conservative — Show only during processing):** Keep the cards but only show them when the job is still processing AND partial results exist:

```tsx
{
  job.status === "processing" && firstRow && firstRow.Brand !== "Err" && (
    <div className="grid gap-6 animate-in slide-in-from-bottom-4 duration-500">
      <h2 className="text-xl font-bold text-white flex items-center gap-2">
        <CheckCircledIcon className="text-emerald-400" /> Preliminary
        Classification
      </h2>
      {/* ... cards ... */}
    </div>
  );
}
```

**Go with Option A.** The Summary Verdict Bar + Reasoning Card together provide everything the user needs. The card grid was the original layout before the summary bar existed.

### 3. Improve the Summary Bar to be the Single Source of Truth

Since the summary bar is now the ONLY classification display, make it slightly more prominent for completed jobs:

- Increase padding: `px-6 py-4` (up from `py-3`)
- Make the Brand and Category text slightly larger: `text-xl` for Brand, `text-xl` for Category
- Ensure the confidence gauge dot is visible

No structural change — just a slight size bump since it's now the primary display.

### 4. Fix the Pill Filter — Add Common Words Filter

The "and" word appeared as a pill because the current `isValidSignalPill` filter doesn't catch it (it's only 3 chars and passes all checks). Add a **common English words blocklist**:

In the `isValidSignalPill` function (or wherever the pill filter logic is):

```typescript
const COMMON_WORDS = new Set([
  "a",
  "an",
  "and",
  "are",
  "as",
  "at",
  "be",
  "by",
  "for",
  "from",
  "has",
  "have",
  "he",
  "her",
  "his",
  "in",
  "is",
  "it",
  "its",
  "of",
  "on",
  "or",
  "she",
  "so",
  "the",
  "their",
  "them",
  "then",
  "there",
  "they",
  "this",
  "to",
  "too",
  "was",
  "we",
  "were",
  "what",
  "when",
  "where",
  "which",
  "who",
  "will",
  "with",
  "would",
  "but",
  "if",
  "not",
  "no",
  "yes",
  "that",
  "than",
  "also",
  "been",
  "being",
  "both",
  "each",
  "had",
  "may",
  "most",
  "must",
  "likely",
  "likely meant",
  "however",
  "therefore",
  "thus",
]);

function isValidSignalPill(text: string): boolean {
  const trimmed = text.trim();

  // Existing checks...
  if (trimmed.length > 50) return false;
  if (trimmed.length < 2) return false;
  if (/^[—\-,;:)\.\!\?]/.test(trimmed)) return false;
  if (/[,;:\(]$/.test(trimmed)) return false;
  const wordCount = trimmed.split(/\s+/).length;
  if (wordCount > 10) return false;

  // NEW: Filter out common English words/phrases
  if (COMMON_WORDS.has(trimmed.toLowerCase())) return false;

  return true;
}
```

This catches "and", "likely meant", and any other common words that aren't brand names or slogans.

## Summary of Changes

| Change                      | What                                                                | Where                          |
| --------------------------- | ------------------------------------------------------------------- | ------------------------------ |
| Hide stage boxes            | Don't show "Current Stage / Stage Detail" for completed/failed jobs | Header section                 |
| Remove classification cards | Delete the 3-card grid entirely; Summary Bar is the classification  | "Final Classification" section |
| Bump summary bar            | Slightly larger text since it's now the primary display             | Summary Verdict Bar            |
| Fix pill filter             | Add common-words blocklist (catches "and", "likely meant", etc.)    | Pill validation function       |

## File to modify

`frontend/src/pages/JobDetail.tsx` — all changes are in this single file.

## Constraints

- **Only modify `frontend/src/pages/JobDetail.tsx`**.
- **No backend changes.**
- **The Summary Verdict Bar must remain** — it IS the classification display now.
- **The Reasoning Card must remain** — it provides the explanation below the verdict.
- **Handle the processing state**: If the job is still processing and partial results exist, you can optionally show a simplified "Preliminary" card, but the completed state should be clean: just verdict bar + reasoning.
- **Match existing theme.**
