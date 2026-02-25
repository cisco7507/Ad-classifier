# UI Enhancement: Agent Scratchboard Color-Coding

## Overview

Improve the Agent Scratchboard section in `JobDetail.tsx` (lines 300–311) by parsing and color-coding tool calls, observations, and thoughts. Currently the scratchboard is monochrome monospace text that's hard to scan.

## Current State

The Agent Scratchboard renders `agentScratchboardEvents` as plain `<div>` elements with `whitespace-pre-wrap` (line 307). Each event is raw text like:

```
--- Step 1 ---
Action: [TOOL: OCR]
Result: Observation: [Scene 1]: Toyota Let's Go Places | [Scene 2]: toyota.com

--- Step 2 ---
Action: [TOOL: SEARCH | query="Toyota slogan Let's Go Places"]
Result: Observation from Web: Toyota Motor Corporation is a Japanese...

--- Step 3 ---
Action: [TOOL: FINAL | brand="Toyota", category="Automotive", reason="OCR + web confirmed"]
Result: Final tool accepted.
✅ FINAL CONCLUSION REACHED.
```

## Changes

### Parse and Color-Code Tool Calls

For each scratchboard event, detect tool markers and apply visual styling:

| Pattern                         | Color                       | Icon                          |
| ------------------------------- | --------------------------- | ----------------------------- |
| `[TOOL: OCR]`                   | Cyan (`text-cyan-400`)      | 📝 or a document icon         |
| `[TOOL: SEARCH \| query="..."]` | Amber (`text-amber-400`)    | 🔍 or a magnifying glass icon |
| `[TOOL: VISION]`                | Purple (`text-fuchsia-400`) | 👁️ or an eye icon             |
| `[TOOL: FINAL \| ...]`          | Green (`text-emerald-400`)  | ✅ or a check icon            |
| `[TOOL: ERROR \| ...]`          | Red (`text-red-400`)        | ❌ or an exclamation icon     |

### Styling per Line Type

Within each event block, apply different styles based on content:

- **Lines starting with `--- Step N ---`**: Render as a section divider. Style: `text-slate-500 uppercase tracking-wider text-[10px] border-b border-slate-800 pb-1 mb-2 mt-4`
- **Lines starting with `Action:`**: Bold the "Action:" label. Highlight the `[TOOL: ...]` match with its color. Rest of the line in `text-slate-300`.
- **Lines starting with `Result:` or `Observation:`**: Style as an indented block with a left border in the tool's color. Use `border-l-2 pl-3 ml-2`. Text in `text-slate-400`.
- **Lines starting with `🤔 Thought:`**: Italic, `text-slate-500`.
- **Lines containing `✅ FINAL CONCLUSION`**: Full-width green banner: `bg-emerald-500/10 border border-emerald-500/20 rounded px-3 py-2 text-emerald-300 font-semibold`.

### Implementation approach

Create a helper function `renderScratchboardEvent(event: string, index: number)` that:

1. Splits the event text by newlines.
2. For each line, checks against the patterns above.
3. Returns styled JSX.

Use regex to detect tool calls: `\[TOOL:\s*(OCR|SEARCH|VISION|FINAL|ERROR).*?\]`

Extract the tool name to determine the color. For `SEARCH`, also extract and display the query in a subtle badge.

For `FINAL`, extract brand/category/reason kwargs and render them as labeled values:

```
✅ FINAL
  Brand: Toyota
  Category: Automotive
  Reason: OCR confirmed brand name and slogan
```

### Search Query Highlighting

When a `SEARCH` tool is detected, extract the query from `query="..."` and display it in a highlighted pill:

```
🔍 SEARCH  [Toyota slogan Let's Go Places]
```

Style the query pill: `bg-amber-500/10 text-amber-300 px-2 py-0.5 rounded text-[10px] font-mono`

### Before/After

**Before:** Wall of monospace text, all the same shade of grey.

**After:** Visually scannable steps with color-coded tool calls, indented observations, and a green conclusion banner. The user can instantly see: OCR ran → Search confirmed → Final decision.

## File to modify

`frontend/src/pages/JobDetail.tsx` — modify the scratchboard rendering section (lines 300–311).

## Constraints

- **Only modify `frontend/src/pages/JobDetail.tsx`**.
- **No backend changes.**
- **No new dependencies** — use Radix icons already imported if appropriate, or emoji fallbacks.
- **Preserve the auto-scroll behavior** — the `scratchboardRef` and `useEffect` auto-scroll must still work.
- **Handle edge cases** — events that don't match any pattern should render as plain text (current behavior).
- **Match the existing dark theme.**
- **Performance** — scratchboard events can grow to ~50+ entries during agent execution. Ensure the parsing doesn't cause re-render jank. Memoize the render function if needed.
