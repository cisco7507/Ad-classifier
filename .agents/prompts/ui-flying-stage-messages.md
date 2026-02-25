# UI Enhancement: Collapsible Event History + Flying Stage Messages

## Problem

The "Stage / Event History" section takes up a lot of vertical space (a full `h-96` scrollable container) and pushes important content like the classification results further down the page. During processing, the user cares about the _current_ stage, not the full log. After completion, the log is rarely reviewed — the results and reasoning are what matter.

## Solution

Two changes:

1. **Start the event history collapsed** — wrap it in a `<details>` element like the Raw JSON section. Users can expand it when they need the full log.
2. **Fly stage messages into the timeline** — during processing, when a new event fires, briefly show it as a floating message near the active timeline dot. The message animates in, stays for ~3 seconds, then fades out. This gives the user real-time feedback without needing the full log visible.

## Part 1: Collapse the Event History

### Current (lines ~313–324)

```tsx
<div className="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden shadow-inner flex flex-col">
  <div className="bg-slate-900/80 px-4 py-3 border-b border-slate-800 font-semibold text-slate-300">
    Stage / Event History
  </div>
  <div
    className="p-4 h-96 overflow-y-auto space-y-2 font-mono text-xs text-slate-400"
    ref={historyRef}
  >
    {events.map((evt, i) => (
      <div key={i} className="...">
        ...
      </div>
    ))}
  </div>
</div>
```

### New: Collapsed by default

```tsx
<details className="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden shadow-sm group">
  <summary className="px-6 py-4 font-semibold text-slate-400 group-hover:bg-slate-800/50 transition-colors list-none flex items-center gap-2 cursor-pointer">
    {/* Use an appropriate icon */}
    <MagicWandIcon className="text-fuchsia-400" />
    Stage / Event History
    <span className="text-xs text-slate-600 font-normal ml-2">
      ({events.length} events)
    </span>
  </summary>
  <div
    className="p-4 max-h-96 overflow-y-auto space-y-2 font-mono text-xs text-slate-400 border-t border-slate-800"
    ref={historyRef}
  >
    {events.map((evt, i) => (
      <div
        key={i}
        className="border-b border-slate-800/50 pb-2 mb-2 last:border-0 whitespace-pre-wrap"
      >
        {evt}
      </div>
    ))}
  </div>
</details>
```

Key changes:

- Wrapped in `<details>` — collapsed by default.
- Shows event count in the summary: `"(12 events)"`.
- Same styling pattern as the existing "Raw JSON Context" `<details>` at the bottom.
- `ref={historyRef}` stays so auto-scroll still works when expanded.

**Exception**: If the job is still `processing`, auto-expand the details element by setting `open` attribute. When completed/failed, default to collapsed:

```tsx
<details
  className="..."
  open={job.status === 'processing'}
>
```

This way users see the live log during processing, but it collapses once the job finishes and the results are more important.

## Part 2: Flying Messages on the Timeline

During processing, when a new event arrives, show it as a **floating toast** that appears near the active (pulsing) stage dot on the timeline, then fades away.

### State Management

Add state to track the latest event message:

```typescript
const [flyingMessage, setFlyingMessage] = useState<string | null>(null);
const flyingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
const prevEventCountRef = useRef<number>(0);
```

When the events array grows (new event arrives), extract the latest event and trigger the flying message:

```typescript
useEffect(() => {
  if (
    events.length > prevEventCountRef.current &&
    job?.status === "processing"
  ) {
    const latestEvent = events[events.length - 1];
    // Extract just the stage detail from the event string
    // Events look like: "2026-02-25T20:09:11... claim: worker claimed job"
    const detail = latestEvent.replace(/^\d{4}-\d{2}-\d{2}T[\d:.+]+\s*/, "");

    setFlyingMessage(detail);

    // Clear any existing timeout
    if (flyingTimeoutRef.current) clearTimeout(flyingTimeoutRef.current);

    // Fade out after 3 seconds
    flyingTimeoutRef.current = setTimeout(() => {
      setFlyingMessage(null);
    }, 3000);
  }
  prevEventCountRef.current = events.length;
}, [events, job?.status]);
```

### Rendering the Flying Message

Position it **below the active timeline dot**, as an absolutely positioned element within the timeline container.

```tsx
{
  /* Inside the timeline section, after the dots row */
}
<div className="relative h-8 mt-6">
  {flyingMessage && job.status === "processing" && (
    <div
      className="absolute left-1/2 -translate-x-1/2 animate-in fade-in slide-in-from-bottom-2 duration-300 fill-mode-forwards"
      style={{
        // Position horizontally near the active stage dot
        left: `${((currentIdx + 0.5) / stages.length) * 100}%`,
      }}
    >
      <div className="bg-slate-800/90 backdrop-blur-sm border border-blue-500/30 rounded-lg px-3 py-1.5 text-xs text-blue-300 font-mono whitespace-nowrap shadow-lg shadow-blue-500/5">
        {flyingMessage}
      </div>
    </div>
  )}
</div>;
```

### Animation

The message should:

1. **Fade in + slide up** when it appears (use existing `animate-in` utilities or CSS keyframes)
2. **Stay visible** for ~3 seconds
3. **Fade out** when removed from state

For the fade-out, since React removes the element when `flyingMessage` becomes null, you have two options:

**Option A (Simple)**: Just let it disappear instantly when the next message replaces it, and fade in the new one. This creates a "ticker" effect where messages replace each other.

**Option B (Smoother)**: Use CSS animation with a 3-second lifecycle:

```css
@keyframes flyMessage {
  0% {
    opacity: 0;
    transform: translateY(8px);
  }
  10% {
    opacity: 1;
    transform: translateY(0);
  }
  80% {
    opacity: 1;
    transform: translateY(0);
  }
  100% {
    opacity: 0;
    transform: translateY(-4px);
  }
}
```

```tsx
<div
  key={flyingMessage} // Force re-mount on each new message
  className="..."
  style={{
    animation: 'flyMessage 3s ease-in-out forwards',
    left: `${((currentIdx + 0.5) / stages.length) * 100}%`,
  }}
>
```

**Option A is recommended** — simpler, and during fast stage transitions the rapid replacement feels responsive.

### Visual Concept

```
  ●━━━━━●━━━━━●━━━━━◉━━━━━○━━━━━○━━━━━○━━━━━○
claim  ingest extract  OCR  vision  LLM  persist done
                        │
                  ┌─────┴──────┐
                  │ ocr engine │   ← flies in, fades after 3s
                  │ =easyocr   │
                  └────────────┘
```

When the stage advances from OCR to VISION:

- The blue pulsing dot moves from OCR to VISION
- A new flying message appears under the VISION dot: `"vision enabled; computing visual category scores"`
- The previous OCR message has already faded

### Edge Cases

1. **Rapid events**: If events fire faster than the 3-second timeout, the new message replaces the old one instantly (via the `key={flyingMessage}` re-mount). This is fine.
2. **Very long event text**: Truncate with `max-w-xs truncate` on the flying message container.
3. **Job completed while message is showing**: Clear the message when `job.status` changes away from `processing`.
4. **No timeline rendered**: If the stage timeline isn't rendered (e.g., unknown stage), don't render flying messages — fall back to the expanded log.

## Files to modify

`frontend/src/pages/JobDetail.tsx` — all changes go here. If CSS keyframes are used, add them to `App.css` or `index.css`, or use an inline `<style>` block.

## Constraints

- **Only modify frontend files** (`JobDetail.tsx` and optionally CSS).
- **No backend changes.**
- **No new dependencies.**
- **Auto-scroll on the collapsed log must still work** when the log is expanded manually.
- **The Agent Scratchboard** (for agent mode) should remain as-is — it's a separate section with its own purpose.
- **Match the existing dark theme and animation conventions** (the codebase already uses `animate-in` utilities).
