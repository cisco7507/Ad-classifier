# UI Enhancement: Redesign the Summary Verdict Bar

## Problem

The current summary bar renders as a single pipe-separated text string:

```
✅ Volvo → Automotive (ID: 399) | Confidence: N/A | Embeddings Match (1.00) | 39 frames
```

This reads like a log line, not a UI element. It has no visual hierarchy, no icons, and doesn't handle edge cases like "N/A" confidence gracefully.

## Current Implementation

The summary bar is located in `JobDetail.tsx`, rendered when `job.status === 'completed'` and `firstRow` exists. It currently uses a single `<span>` or `<div>` with pipe-separated interpolated text.

## Redesigned Summary Bar

Replace the text line with a structured two-zone horizontal bar.

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  ✅  Volvo  →  Automotive  [ID: 399]  │  Confidence │ Match    │ Frames │
│                                        │     N/A     │ Embed.   │   39   │
│      ← LEFT ZONE (verdict) →          │     ← RIGHT ZONE (stats) →     │
└─────────────────────────────────────────────────────────────────────────┘
```

### Left Zone — The Verdict

The primary answer, visually dominant:

```tsx
<div className="flex items-center gap-3">
  {/* Status icon */}
  <CheckCircledIcon className="w-5 h-5 text-emerald-400 shrink-0" />

  {/* Brand */}
  <span className="text-lg font-bold text-white">{firstRow.Brand}</span>

  {/* Arrow */}
  <span className="text-slate-600">→</span>

  {/* Category */}
  <span className="text-lg font-bold text-emerald-400">
    {firstRow.Category}
  </span>

  {/* Category ID badge */}
  {firstRow["Category ID"] && (
    <span className="text-[10px] font-mono text-slate-500 bg-slate-800 px-2 py-0.5 rounded">
      ID: {firstRow["Category ID"]}
    </span>
  )}
</div>
```

Key styling:

- Brand in **bold white** — the most important piece of information.
- Category in **bold emerald** — visually connected to the "success" palette.
- Arrow (`→`) in muted `text-slate-600` — not the focus.
- Category ID as a tiny monospace badge — informational but not dominant.
- `CheckCircledIcon` from Radix (already imported in the file).

### Right Zone — Stats

Three compact stat blocks separated by subtle vertical dividers. Each block has a tiny uppercase label on top and the value below.

```tsx
<div className="flex items-center gap-0 shrink-0">
  {/* Confidence */}
  <div className="px-4 border-l border-slate-700/50 text-center">
    <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">
      Confidence
    </div>
    <div className={`text-sm font-bold ${confidenceColor}`}>
      {confidenceDisplay}
    </div>
  </div>

  {/* Match Method */}
  <div className="px-4 border-l border-slate-700/50 text-center">
    <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">
      Match
    </div>
    <div className="text-sm font-mono text-cyan-400">{matchDisplay}</div>
  </div>

  {/* Frame Count */}
  <div className="px-4 border-l border-slate-700/50 text-center">
    <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">
      Frames
    </div>
    <div className="text-sm font-mono text-slate-300">{frameCount}</div>
  </div>
</div>
```

### Stat Block Details

**Confidence:**

- Parse `firstRow.Confidence` to a float. Handle strings, numbers, null, "N/A", and 0.
- Display logic:
  - If valid number ≥ 0: show the number formatted to 2 decimal places.
  - If "N/A", null, undefined, or empty: show `"—"` (em dash).
- Color logic (`confidenceColor`):
  - `≥ 0.8` → `text-emerald-400` (green — high confidence)
  - `0.5–0.8` → `text-amber-400` (amber — medium)
  - `< 0.5` → `text-red-400` (red — low)
  - Invalid/N/A → `text-slate-500` (grey — unknown)
- Add a tiny color dot indicator (`w-1.5 h-1.5 rounded-full`) next to the value using the same color, for a visual cue that doesn't rely on text color alone.

**Match Method:**

- Access `firstRow.category_match_method` and `firstRow.category_match_score`.
- Display the method as a short label. Abbreviate long names:
  - `"semantic"` → `"Semantic"`
  - `"exact"` → `"Exact"`
  - `"embeddings"` → `"Embed."`
  - `"vision"` → `"Vision"`
  - `"none"` or missing → `"—"`
- If `category_match_score` exists and is a number, show it in parentheses: `"Semantic (0.94)"`.
- Style in `text-cyan-400 font-mono`.

**Frame Count:**

- Access `artifacts?.latest_frames?.length` or count from result data.
- Show as a simple number: `"39"`.
- If not available, show `"—"`.
- Style in `text-slate-300 font-mono`.

### Overall Bar Styling

```tsx
<div className="bg-slate-900 border border-emerald-500/20 border-t-2 border-t-emerald-500/50 rounded-xl px-6 py-3 flex items-center justify-between">
  {/* Left zone */}
  {/* Right zone */}
</div>
```

Key styling decisions:

- **Top border accent**: `border-t-2 border-t-emerald-500/50` — a subtle green line at the top that signals "success/verdict".
- **Background**: `bg-slate-900` — matches other cards.
- **Border**: `border border-emerald-500/20` — very subtle green tint on all sides.
- **Rounded corners**: `rounded-xl`.
- **Horizontal layout**: `flex items-center justify-between` — verdict left, stats right.

### Responsive Behavior

On mobile (`md:` breakpoint and below):

- Stack the left and right zones vertically.
- Use `flex-col md:flex-row` on the outer container.
- Stats blocks should wrap into a row below the verdict.
- Reduce brand/category text size to `text-base` on mobile.

```tsx
<div className="... flex flex-col md:flex-row items-start md:items-center justify-between gap-3 md:gap-0">
```

### Failed Job Variant

If the job failed (`firstRow.Brand === 'Err'`), don't render this bar at all — the existing error display handles it.

### Edge Cases

1. **Very long brand name** (e.g., "Procter & Gamble Consumer Healthcare"): Use `truncate` with `max-w-xs` and a `title` attribute for the full name on hover.
2. **Very long category** (e.g., "Retail - Home Improvement & Building Supplies"): Same truncation approach, `max-w-sm truncate`.
3. **Missing Category ID**: Hide the badge entirely — don't show "ID: undefined".
4. **Confidence is 0**: Show `0.00` in red — this is a valid but concerning value, not the same as N/A.
5. **Multiple result rows**: Use `firstRow` (index 0) — batch results are shown in the table below.

## File to modify

`frontend/src/pages/JobDetail.tsx` — modify only the summary bar rendering section.

## Constraints

- **Only modify `frontend/src/pages/JobDetail.tsx`**.
- **No backend changes.**
- **No new dependencies** — use Radix icons already imported (`CheckCircledIcon`, etc.) and Tailwind.
- **Match the existing dark theme.**
- **The bar must render between the header card and the classification section** — same placement as current.
- **Handle all data types safely** — confidence may be string, number, null, or "N/A".
