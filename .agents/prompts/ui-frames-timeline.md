# UI Enhancement: Frame-OCR Correlation & Stage Timeline

## Overview

Two interactive enhancements for the Job Detail page that improve how users explore frame data and understand pipeline progress. These are slightly more complex than the other UI prompts but share the same file.

---

## Part 1: OCR Text on Frame Hover

### Problem

The "Latest Frames" tab shows thumbnails, and the "OCR Output" tab shows timestamped text. These are in separate tabs — the user can't see which text came from which frame without mentally matching timestamps.

### Solution

When hovering a frame thumbnail, show a tooltip/overlay with the OCR text for that frame. The data correlation already exists: frames have timestamps (e.g., `27.0s`), and OCR lines are formatted as `[27.0s] text here`.

### Implementation

1. **Parse the OCR text into a timestamp-keyed map.** In the component (or a `useMemo`), split `ocrText` by newlines and extract timestamp → text pairs:

```typescript
const ocrByTimestamp = useMemo(() => {
  const map = new Map<string, string>();
  for (const line of (ocrText || "").split("\n")) {
    const match = line.match(/^\[([\d.]+)s\]\s*(.*)$/);
    if (match) {
      map.set(match[1], match[2]);
    }
  }
  return map;
}, [ocrText]);
```

2. **Match frames to OCR text.** Each frame has a `timestamp` field (number) or a `label` field (e.g., `"27.0s"`). Extract the number and look up in the map.

3. **Render as a hover overlay on each frame thumbnail.** In the frames grid (lines 282–297), add an absolutely positioned overlay that appears on hover:

```tsx
<div className="aspect-video ... relative group">
  <img ... />
  {/* Existing timestamp label */}
  <div className="absolute bottom-0 ...">...</div>

  {/* NEW: OCR overlay on hover */}
  {frameOcrText && (
    <div className="absolute inset-0 bg-black/85 opacity-0 group-hover:opacity-100 transition-opacity duration-200 p-3 flex items-center justify-center">
      <p className="text-[10px] text-cyan-300 font-mono leading-relaxed text-center line-clamp-6">
        {frameOcrText}
      </p>
    </div>
  )}
</div>
```

4. **Fallback:** If no OCR text matches the frame's timestamp, don't render the overlay. The frame just shows normally.

### UX Detail

- The overlay appears on hover with a `200ms` transition.
- Text is cyan monospace on a dark semi-transparent background.
- Use `line-clamp-6` (or similar) to truncate very long OCR text.
- On mobile (touch), consider showing OCR text on tap instead of hover.

---

## Part 2: Pipeline Stage Timeline

### Problem

The "Stage / Event History" section (lines 313–324) is a raw text log of timestamped events. Understanding the pipeline's progress requires reading each line. For in-progress jobs, it's hard to see at a glance what stage the pipeline is in.

### Solution

Add a visual horizontal timeline above the event log that shows pipeline stages as connected dots/segments. The current stage pulses. Completed stages are green. Future stages are grey.

### Stage Sequence

The pipeline stages (from `worker.py` `_set_stage` calls) follow this order:

```
claim → ingest → frame_extract → ocr → vision → llm → persist → completed
```

For agent mode, stages are similar but may include additional `agent` stages.

### Implementation

1. **Define the stage sequence** as a constant:

```typescript
const PIPELINE_STAGES = [
  "claim",
  "ingest",
  "frame_extract",
  "ocr",
  "vision",
  "llm",
  "persist",
  "completed",
];
const AGENT_STAGES = [
  "claim",
  "ingest",
  "frame_extract",
  "ocr",
  "vision",
  "llm",
  "persist",
  "completed",
];
```

2. **Determine the current stage index** from `job.stage`:

```typescript
const stages = job.mode === "agent" ? AGENT_STAGES : PIPELINE_STAGES;
const currentIdx = stages.indexOf(job.stage || "");
```

3. **Render the timeline** as a horizontal flex row of dots connected by lines:

```tsx
<div className="flex items-center gap-0 w-full px-4 py-4">
  {stages.map((stage, idx) => {
    const isDone = currentIdx > idx || job.status === "completed";
    const isCurrent = currentIdx === idx && job.status === "processing";
    const isFuture = currentIdx < idx;
    const isFailed = job.status === "failed" && currentIdx === idx;

    return (
      <Fragment key={stage}>
        {idx > 0 && (
          <div
            className={`flex-1 h-0.5 ${isDone ? "bg-emerald-500" : "bg-slate-800"}`}
          />
        )}
        <div className="flex flex-col items-center gap-1 relative">
          <div
            className={`w-3 h-3 rounded-full border-2 ${
              isDone
                ? "bg-emerald-500 border-emerald-400"
                : isCurrent
                  ? "bg-blue-500 border-blue-400 animate-pulse"
                  : isFailed
                    ? "bg-red-500 border-red-400"
                    : "bg-slate-800 border-slate-700"
            }`}
          />
          <span
            className={`text-[9px] uppercase tracking-wider absolute -bottom-5 whitespace-nowrap ${
              isDone
                ? "text-emerald-500"
                : isCurrent
                  ? "text-blue-400"
                  : "text-slate-600"
            }`}
          >
            {stage.replace("_", " ")}
          </span>
        </div>
      </Fragment>
    );
  })}
</div>
```

4. **Placement**: Insert above the "Stage / Event History" section (before line 313). Wrap both the timeline and the event log in a shared container.

5. **Stage detail tooltip**: On hover of each dot, show `job.stage_detail` if the dot is the current stage. Use a simple `title` attribute or a custom tooltip.

### Visual Style

```
  ●━━━━━●━━━━━●━━━━━◉━━━━━○━━━━━○━━━━━○━━━━━○
claim  ingest extract  OCR  vision  LLM  persist done
 ✓       ✓      ✓     ⟵ processing
```

- `●` (green filled) = completed stage
- `◉` (blue pulsing) = current stage
- `○` (grey) = future stage
- `●` (red) = failed stage (if applicable)
- Lines between dots: green for completed segments, grey for future

### Responsive

On small screens, the timeline labels may overlap. Options:

- Rotate labels 45° on small screens
- Show only the dots on mobile, with stage names in a tooltip
- Use `overflow-x-auto` for horizontal scrolling

---

## File to modify

`frontend/src/pages/JobDetail.tsx` — both features go in this file.

## Constraints

- **Only modify `frontend/src/pages/JobDetail.tsx`**.
- **No backend changes.**
- **No new dependencies.**
- **`Fragment` import** — add to the React import if not already there.
- **Memoize expensive computations** (`ocrByTimestamp` map) with `useMemo`.
- **Match the existing dark theme.**
- **Handle missing data** — if timestamps don't correlate, don't force it. If `job.stage` doesn't match any known stage, show the timeline with no active dot.
