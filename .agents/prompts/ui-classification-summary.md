# UI Enhancement: Classification Results & Summary Bar

## Overview

This prompt covers 5 related improvements to the Job Detail page (`frontend/src/pages/JobDetail.tsx`). All share the same theme: **surfacing data that already exists in the result object** but is currently only visible in the Raw JSON section. No backend changes needed.

## Current State

When a job completes, the "Final Classification" section (lines 222–242) shows 3 cards:

- **Category** (`firstRow.Category`)
- **Brand** (`firstRow.Brand`)
- **Confidence** (`firstRow.Confidence`)

The following fields exist in the result but are **not displayed anywhere**:

- `firstRow.Reasoning` — the LLM's explanation of why it chose this brand/category
- `firstRow["Category ID"]` — the Freewheel taxonomy ID
- `firstRow.category_match_method` — how the category was resolved (e.g., "semantic", "exact")
- `firstRow.category_match_score` — similarity score of the category mapping

---

## Changes

### 1. Surface the LLM Reasoning (Priority: Critical)

Add a reasoning card below the existing 3-card grid. This is the single most impactful change — users currently have to open Raw JSON to see why the LLM chose a particular brand/category.

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Category   │  │    Brand    │  │ Confidence  │
│ Automotive  │  │    Toyota   │  │    0.92     │
└─────────────┘  └─────────────┘  └─────────────┘
┌─────────────────────────────────────────────────┐
│ 💡 LLM Reasoning                                │
│ OCR detected "Toyota" and "Let's Go Places"     │
│ slogan. Category mapped from "Cars & Trucks"    │
│ → "Automotive". [Mapped from 'Cars']            │
└─────────────────────────────────────────────────┘
```

Implementation:

- Below the `grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3` div (line 240), add a full-width card.
- Render `firstRow.Reasoning` or `firstRow["Reasoning"]` — handle both casings.
- Use `text-sm text-slate-300` for the text, with a subtle background (`bg-slate-900 border border-slate-800`).
- If reasoning is empty or missing, show a muted "No reasoning available" placeholder.
- Add a `CopyButton` for the reasoning text (users paste it into reports).

### 2. Category ID Badge

Add the Category ID as a small monospace badge next to the category name inside the existing Category card.

Change from:

```
Category
Automotive
```

To:

```
Category
Automotive  [ID: 147]
```

Implementation:

- Inside the Category card (line 230), append a `<span>` after the category name.
- Style: `text-xs font-mono text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded ml-2`
- Only render the badge if `firstRow["Category ID"]` is truthy and not empty.

### 3. Confidence as a Color-Coded Gauge

Replace the plain text confidence number with a horizontal bar gauge that visually communicates quality.

Implementation:

- Keep the numeric value displayed.
- Below it, add a horizontal bar (`h-2 rounded-full`) showing the confidence as a percentage width.
- Color-code:
  - `≥ 0.8` → green gradient (`from-emerald-500 to-emerald-400`)
  - `0.5–0.8` → amber gradient (`from-amber-500 to-amber-400`)
  - `< 0.5` → red gradient (`from-red-500 to-red-400`)
- Parse confidence to float safely — it may be a string, number, or "N/A".
- Background of the bar track: `bg-slate-800`.

### 4. Category Match Method Indicator

Add a small indicator showing how the category was resolved, below the Category card or integrated into the reasoning card.

Implementation:

- Access `firstRow.category_match_method` and `firstRow.category_match_score`.
- Render as a subtle inline badge: `Semantic Match (0.94)` or `Exact Match`.
- Style: `text-[10px] uppercase tracking-wider text-slate-500`
- Place it below the category name in the Category card, or as a sub-line in the reasoning card.
- Only render if `category_match_method` is truthy and not "none" or "pending".

### 5. Quick-Glance Summary Bar

When a job is completed successfully, show a compact summary bar immediately below the header section (before the classification cards), giving the answer at a glance without scrolling.

```
✅ Toyota → Automotive (ID: 147) | Confidence: 0.92 | Semantic Match | 5 frames
```

Implementation:

- Render only when `job.status === 'completed'` and `firstRow` exists and `firstRow.Brand !== 'Err'`.
- Place it between the header card (line 220) and the classification section (line 222).
- Style: `bg-emerald-500/10 border border-emerald-500/20 rounded-xl px-6 py-3 text-sm text-emerald-300`
- Content: `{Brand} → {Category} (ID: {Category ID}) | Confidence: {Confidence} | {match_method}`
- Add frame count from `artifacts?.latest_frames?.length` if available.
- This is a single horizontal line — not a card grid. Think of it as a "TL;DR" banner.

---

## File to modify

`frontend/src/pages/JobDetail.tsx` — this is the only file that changes.

## Data Reference

The `firstRow` variable (line 137) is typed as `ResultRow` from `lib/api.ts`. Verify the field names match the API response. The result JSON from the backend looks like:

```json
[
  {
    "URL / Path": "...",
    "Brand": "Toyota",
    "Category ID": "147",
    "Category": "Automotive",
    "Confidence": 0.92,
    "Reasoning": "OCR detected...",
    "category_match_method": "semantic",
    "category_match_score": 0.94
  }
]
```

Field names use both spaces and underscores — be careful with access patterns (bracket notation for spaced keys).

## Constraints

- **Only modify `frontend/src/pages/JobDetail.tsx`**.
- **No backend changes.**
- **No new dependencies** — use only what's already installed (React, Radix icons, Tailwind).
- **Match the existing dark theme** — slate-900 backgrounds, slate-800 borders, the existing gradient palette.
- **Responsive** — the summary bar and reasoning card should work on mobile (stack vertically).
- **Handle missing data gracefully** — any field might be null, undefined, empty, or "N/A".
