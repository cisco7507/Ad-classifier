# UI Enhancement: Redesign the LLM Reasoning Card

## Problem

The current LLM Reasoning card in `JobDetail.tsx` renders the reasoning text as a single dense paragraph of monochrome text. All the valuable signals — brand name, website, slogans, OCR fragments — are buried in prose and hard to scan. The user has to read the entire paragraph to extract the key information.

## Current Rendering

The reasoning card currently looks like this (simplified):

```tsx
<div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
  <div className="text-xs uppercase text-slate-500 mb-2">💡 LLM Reasoning</div>
  <div className="text-sm text-slate-300">{firstRow.Reasoning}</div>
  <CopyButton text={firstRow.Reasoning} label="Copy Reasoning" />
</div>
```

## Example Reasoning Text

```
The OCR text contains multiple typos and artifacts (e.g., 'The [HUGE] BRICK', 'THEBRICK COM', 'SelECTION SERVICE AVAILABILITY PRICING AND PROMOTIONAL OffERS'), but the brand name 'The Brick' is unmistakable. Based on internal brand knowledge, The Brick is a Canadian retail chain specializing in home improvement, building supplies, and DIY products. The slogan 'PROUDLY CANADIAN SINCE 1971' and the website 'thebrick.com' confirm this. The tagline 'SAVING YOU MORE' is a common promotional phrase for retail. The category is 'Retail - Home Improvement & Building Supplies' as this is the core business of The Brick.
```

## Redesigned Card

The new card has three visual layers:

### Layer 1: Signal Pills (Top)

Extract all quoted terms from the reasoning text (anything inside single quotes `'...'`) and display them as colored pill/chip badges at the top of the card. This is the "TL;DR" — the user sees the key evidence at a glance.

**Categorize each pill by type:**

| Type         | Detection Rule                                                           | Pill Style                                                                                                 |
| ------------ | ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| **Brand**    | Term matches `firstRow.Brand` (case-insensitive)                         | White text on slate-700 bg, bold. `bg-slate-700 text-white font-semibold px-2.5 py-1 rounded-full text-xs` |
| **URL**      | Term matches regex `/\.\w{2,4}$/` (contains `.com`, `.ca`, `.org`, etc.) | Cyan. `bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 px-2.5 py-1 rounded-full text-xs font-mono`  |
| **Evidence** | Everything else (slogans, OCR fragments)                                 | Amber. `bg-amber-500/15 text-amber-300 border border-amber-500/30 px-2.5 py-1 rounded-full text-xs`        |

**Extraction logic:**

```typescript
const quotedTerms = useMemo(() => {
  const reasoning = firstRow?.Reasoning || "";
  const matches = reasoning.match(/'([^']+)'/g);
  if (!matches) return [];
  // Deduplicate and strip surrounding quotes
  const unique = [...new Set(matches.map((m) => m.slice(1, -1)))];
  return unique.map((term) => {
    const brand = (firstRow?.Brand || "").toLowerCase();
    const termLower = term.toLowerCase();
    if (brand && termLower === brand)
      return { text: term, type: "brand" as const };
    if (/\.\w{2,4}$/.test(term)) return { text: term, type: "url" as const };
    return { text: term, type: "evidence" as const };
  });
}, [firstRow?.Reasoning, firstRow?.Brand]);
```

**Render as a flex-wrap row of pills:**

```tsx
{
  quotedTerms.length > 0 && (
    <div className="flex flex-wrap gap-2 mb-4">
      {quotedTerms.map((term, idx) => (
        <span key={idx} className={/* style based on term.type */}>
          {term.text}
        </span>
      ))}
    </div>
  );
}
```

Add a subtle divider (`<div className="border-b border-slate-800 mb-4" />`) between the pills and the body text.

### Layer 2: Inline-Highlighted Body Text

Render the full reasoning text, but replace quoted terms inline with styled `<span>` elements using matching colors. This makes the wall of text scannable — the eye jumps to highlighted terms.

**Implementation:**

```typescript
const highlightedReasoning = useMemo(() => {
  const reasoning = firstRow?.Reasoning || "";
  if (!reasoning || quotedTerms.length === 0) return reasoning;

  // Build a regex that matches all quoted terms (with surrounding single quotes)
  // Process the text by splitting on quoted terms and interleaving styled spans
  const parts: (string | { text: string; type: string })[] = [];
  let remaining = reasoning;

  // Simple approach: replace each 'term' occurrence with a marker, then map
  const regex = /'([^']+)'/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(reasoning)) !== null) {
    // Add text before this match
    if (match.index > lastIndex) {
      parts.push(reasoning.slice(lastIndex, match.index));
    }
    // Add the highlighted term
    const term = match[1];
    const termInfo = quotedTerms.find((t) => t.text === term);
    parts.push({ text: `'${term}'`, type: termInfo?.type || "evidence" });
    lastIndex = regex.lastIndex;
  }
  // Add remaining text
  if (lastIndex < reasoning.length) {
    parts.push(reasoning.slice(lastIndex));
  }

  return parts;
}, [firstRow?.Reasoning, quotedTerms]);
```

**Render each part:**

```tsx
<p className="text-sm text-slate-300 leading-relaxed">
  {Array.isArray(highlightedReasoning)
    ? highlightedReasoning.map((part, idx) =>
        typeof part === "string" ? (
          <span key={idx}>{part}</span>
        ) : (
          <span
            key={idx}
            className={
              part.type === "brand"
                ? "bg-slate-700/80 text-white font-semibold px-1 rounded"
                : part.type === "url"
                  ? "bg-cyan-500/15 text-cyan-300 px-1 rounded font-mono"
                  : "bg-amber-500/15 text-amber-300 px-1 rounded"
            }
          >
            {part.text}
          </span>
        ),
      )
    : highlightedReasoning}
</p>
```

**Inline highlight colors must match the pill colors** from Layer 1, creating a visual connection between the TL;DR pills and their context in the full text.

### Layer 3: Card Chrome

Improve the overall card styling:

- **Left accent border**: `border-l-[3px] border-l-emerald-500/50` — visually ties it to the "success" classification palette.
- **Line height**: `leading-relaxed` (1.625) on the body text — currently too cramped.
- **Font**: Use the UI font (default sans), NOT monospace — reasoning is prose.
- **Padding**: `p-6` with breathing room between sections.
- **Copy button**: Position in the top-right corner of the card, not inline with text.
- **Header**: `💡 LLM Reasoning` label styled as `text-xs uppercase tracking-wider text-slate-500 font-bold mb-3`.
- **Background**: Subtle gradient or slightly different shade to distinguish from other cards: `bg-gradient-to-r from-slate-900 to-slate-900/80`.

## Complete Card Structure

```
┌──────────────────────────────────────────────────────┐
│ 💡 LLM REASONING                     [Copy Reasoning]│
│                                                       │
│  ┌──────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │ The Brick│  │ thebrick.com │  │ PROUDLY CANADIAN│ │
│  └──────────┘  └──────────────┘  │ SINCE 1971      │ │
│  ┌──────────────┐                 └─────────────────┘ │
│  │ SAVING YOU   │                                     │
│  │ MORE         │                                     │
│  └──────────────┘                                     │
│  ─────────────────────────────────────────────────    │
│                                                       │
│  The OCR text contains multiple typos and artifacts   │
│  (e.g., 'The [HUGE] BRICK', 'THEBRICK COM'), but     │
│  the brand name 'The Brick' is unmistakable. Based    │
│  on internal brand knowledge, The Brick is a Canadian │
│  retail chain... The slogan 'PROUDLY CANADIAN SINCE   │
│  1971' and the website 'thebrick.com' confirm this.   │
│                                                       │
│  (quoted terms are highlighted inline ↑ with matching │
│   colors to the pills above)                          │
└──────────────────────────────────────────────────────┘
```

## Edge Cases

1. **No quoted terms**: If the reasoning contains no single-quoted strings, skip the pills section entirely. Just render the body text with improved typography.
2. **Many quoted terms (>8)**: Show the first 6 pills, then a `+N more` pill that expands to show all. This prevents the pills section from being taller than the reasoning text itself.
3. **Empty reasoning**: Show a muted placeholder: `"No reasoning provided by the LLM."` in `text-slate-600 italic`.
4. **Reasoning starts with `(Recovered)`**: This indicates the agentic recovery path fired (web search was used). Render a small info badge: `🔍 Web-assisted recovery` in `text-amber-400 text-xs` above the pills.
5. **Very long reasoning (>500 chars)**: Consider making the body text collapsible with a "Show more" toggle, defaulting to showing the first ~200 chars + the pills (which are always visible). This way the pills serve as the summary and the full text is opt-in.

## File to modify

`frontend/src/pages/JobDetail.tsx` — all changes go here.

## Data Reference

`firstRow` comes from `result?.[0]` and has these relevant fields:

- `firstRow.Reasoning` (or `firstRow["Reasoning"]`) — the LLM's free-text explanation
- `firstRow.Brand` — detected brand name (used to identify the brand pill)

## Constraints

- **Only modify `frontend/src/pages/JobDetail.tsx`**.
- **No backend changes.**
- **No new dependencies** — use React, existing Radix icons, and Tailwind only.
- **`useMemo`** — memoize the regex parsing and term extraction to avoid re-computation on every render.
- **Accessibility** — pills should have `role="status"` or similar. Highlighted inline text should not rely on color alone (the quotes are preserved for context).
- **Match the existing dark theme** — slate-900 backgrounds, slate-800 borders, emerald/cyan/amber accent palette.
- **Responsive** — pills flex-wrap on mobile, body text uses responsive padding.
