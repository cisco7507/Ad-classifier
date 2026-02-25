# Bugfix: Timeline Messages Overlapping — Redesign as Stage Journey Log

## Problem

The current timeline implementation shows ALL event messages near their stage dots, causing overlap when a stage has multiple events (e.g., "ingest" has 3 messages all stacked on top of each other). Messages positioned above and below the line collide. The user wants:

1. **Messages should NOT overlap** — no stacking/collision
2. **Messages should STAY** — don't fade out, build up a journey
3. **Live view** — new messages appear as they arrive during processing

## Solution: One Message Per Stage

Each stage dot gets **exactly one message slot** below it — showing the **latest** event for that stage. As the pipeline progresses, each stage's slot fills in with its final message, creating a clean journey trail:

```
  ●━━━━━━━━●━━━━━━━━●━━━━━━━━◉━━━━━━━━○━━━━━━━━○━━━━━━━━○
CLAIM     INGEST   EXTRACT    OCR     VISION    LLM    PERSIST
  │         │         │        │
worker    resolved  extracted  ocr          ← each stage shows
claimed   1 item    6 frames   engine=       its LAST message
                               easyocr
```

When a new event arrives for the current stage, it **replaces** the previous message for that stage in-place (no stacking). Previous stages keep their final message permanently displayed.

## Implementation

### Step 1: Group Events by Stage

Parse each event string to extract the stage name. Events follow the format:

```
2026-02-25T20:09:11.019498+00:00 claim: worker claimed job
2026-02-25T20:09:11.031679+00:00 ingest: validating input parameters
2026-02-25T20:09:12.543210+00:00 ingest: resolved 1 input item(s)
2026-02-25T20:09:13.102345+00:00 frame_extract: extracted 6 frames
```

The stage name is between the timestamp and the colon.

```typescript
interface StageMessage {
  stage: string;
  detail: string;
}

const stageMessages = useMemo(() => {
  const map = new Map<string, string>();

  for (const evt of events) {
    // Strip timestamp: "2026-02-25T20:09:11... stage_name: detail text"
    const withoutTimestamp = evt.replace(
      /^\d{4}-\d{2}-\d{2}T[\d:.+\-]+\s*/,
      "",
    );
    // Extract "stage_name: detail" → split on first colon
    const colonIdx = withoutTimestamp.indexOf(":");
    if (colonIdx > 0) {
      const stage = withoutTimestamp.slice(0, colonIdx).trim().toLowerCase();
      const detail = withoutTimestamp.slice(colonIdx + 1).trim();
      // Map uses the LAST occurrence per stage (overwrites previous)
      map.set(stage, detail);
    }
  }

  return map;
}, [events]);
```

### Step 2: Render One Message Per Stage Dot

Replace the current flying-message / stacking approach with a **fixed grid of message slots** aligned to the stage dots.

The timeline should have TWO rows:

1. **Top row**: The dots + connecting lines (existing)
2. **Bottom row**: Stage labels (existing)
3. **Third row (NEW)**: Message slots aligned to each dot

```tsx
{
  /* Timeline container */
}
<div className="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden p-6">
  {/* Row 1: Dots + lines */}
  <div className="flex items-center w-full mb-2">
    {stages.map((stage, idx) => (
      <Fragment key={stage}>
        {idx > 0 && (
          <div
            className={`flex-1 h-0.5 transition-colors duration-500 ${
              currentIdx > idx || job.status === "completed"
                ? "bg-emerald-500"
                : currentIdx === idx
                  ? "bg-emerald-500"
                  : "bg-slate-800"
            }`}
          />
        )}
        <div
          className={`w-3 h-3 rounded-full border-2 shrink-0 transition-colors duration-500 ${
            currentIdx > idx || job.status === "completed"
              ? "bg-emerald-500 border-emerald-400"
              : currentIdx === idx && job.status === "processing"
                ? "bg-blue-500 border-blue-400 animate-pulse"
                : job.status === "failed" && currentIdx === idx
                  ? "bg-red-500 border-red-400"
                  : "bg-slate-800 border-slate-700"
          }`}
        />
      </Fragment>
    ))}
  </div>

  {/* Row 2: Stage labels */}
  <div className="flex w-full mb-3">
    {stages.map((stage, idx) => (
      <div
        key={stage}
        className={`text-[9px] uppercase tracking-wider text-center transition-colors duration-500 ${
          idx === 0 ? "w-3 shrink-0" : "flex-1"
        } ${
          currentIdx > idx || job.status === "completed"
            ? "text-emerald-500"
            : currentIdx === idx
              ? "text-blue-400"
              : "text-slate-600"
        }`}
      >
        {stage.replace("_", " ")}
      </div>
    ))}
  </div>

  {/* Row 3: Message slots — one per stage */}
  <div className="flex w-full border-t border-slate-800/50 pt-3">
    {stages.map((stage, idx) => {
      const message = stageMessages.get(stage);
      const isDone = currentIdx > idx || job.status === "completed";
      const isCurrent = currentIdx === idx && job.status === "processing";

      return (
        <div
          key={stage}
          className={`text-center px-1 ${
            idx === 0 ? "w-3 shrink-0" : "flex-1"
          } min-w-0`}
        >
          {message && (
            <div
              className={`text-[10px] leading-tight truncate transition-all duration-300 ${
                isCurrent
                  ? "text-blue-300 font-medium"
                  : isDone
                    ? "text-slate-500"
                    : "text-slate-600"
              }`}
              title={message}
            >
              {message}
            </div>
          )}
        </div>
      );
    })}
  </div>
</div>;
```

### Key Design Decisions

1. **No overlap possible**: Each stage has a fixed column/slot in a flex row. Messages are `truncate`d to their column width.

2. **Messages stay permanently**: The `stageMessages` map keeps the last message for every stage. Completed stages remain visible — it's a journey trail.

3. **Live updates**: During processing, when a new event for the current stage arrives, the `useMemo` recomputes and the message for that stage updates in-place (React re-renders).

4. **Truncation + hover**: Long messages are truncated with `truncate` CSS. Full text visible via `title` tooltip on hover.

5. **Color transitions**:
   - **Current stage message** → `text-blue-300 font-medium` (bright, draws attention)
   - **Completed stage message** → `text-slate-500` (dimmed, done)
   - **Future stage** → no message shown (slot empty)

6. **Animation**: When a new message appears in a slot, use `transition-all duration-300` for a subtle fade-in effect.

### Stage Name Normalization

The event stage names may not exactly match the timeline stage names. Add normalization:

```typescript
// Normalize event stage names to match timeline stage constants
function normalizeStage(raw: string): string {
  const lower = raw.toLowerCase().trim();
  const aliases: Record<string, string> = {
    frame_extract: "frame_extract",
    frameextract: "frame_extract",
    "frame extract": "frame_extract",
    completed: "completed",
    complete: "completed",
    done: "completed",
  };
  return aliases[lower] || lower;
}
```

Apply this in the `stageMessages` useMemo when setting the stage key.

### Remove the Old Flying Message Logic

Delete:

- The `flyingMessage` state and `flyingTimeoutRef`
- The `prevEventCountRef` and the useEffect that triggers flying messages
- The absolutely positioned flying message `<div>`
- Any CSS keyframes (`flyMessage`) added for the old approach

Replace all of it with the `stageMessages` useMemo and the three-row layout above.

## File to modify

`frontend/src/pages/JobDetail.tsx` — replace the timeline + flying message sections.

## Constraints

- **Only modify `frontend/src/pages/JobDetail.tsx`** (and optionally CSS if custom keyframes exist for the old approach).
- **No backend changes.**
- **Keep the collapsible event history** — the `<details>` approach from the flying-stage-messages prompt should remain. The timeline shows the summary; the collapsed log has the full detail.
- **The timeline must still show correctly for completed jobs** — all dots green, all messages visible.
- **Match the existing dark theme.**
- **Responsive**: On small screens, messages may need to be hidden or the timeline should scroll horizontally. Use `overflow-x-auto` on the container.
