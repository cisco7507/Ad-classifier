import { Fragment, useEffect, useState, useRef, useCallback, useMemo } from 'react';
import type { ReactElement } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getJob, getJobResult, getJobEvents, getJobArtifacts, exportResultsCSV, copyToClipboard } from '../lib/api';
import type { JobStatus, ResultRow, JobArtifacts } from '../lib/api';
import {
  ArrowLeftIcon, FileTextIcon, MagicWandIcon, DownloadIcon,
  CheckCircledIcon, ExclamationTriangleIcon, CopyIcon,
} from '@radix-ui/react-icons';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function toApiUrl(url?: string | null): string {
  if (!url) return '';
  if (url.startsWith('http://') || url.startsWith('https://')) return url;
  return `${API_BASE}${url}`;
}

function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function formatMatchMethod(value: unknown): string {
  if (typeof value !== 'string') return '';
  const trimmed = value.trim();
  if (!trimmed) return '';
  const normalized = trimmed.toLowerCase();
  if (normalized === 'none' || normalized === 'pending') return '';
  return normalized
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function formatSummaryMatch(method: unknown, score: unknown): string {
  if (typeof method !== 'string') return '—';
  const normalized = method.trim().toLowerCase();
  if (!normalized || normalized === 'none' || normalized === 'pending') return '—';

  const label = normalized === 'semantic'
    ? 'Semantic'
    : normalized === 'exact'
      ? 'Exact'
      : normalized === 'embeddings'
        ? 'Embed.'
        : normalized === 'vision'
          ? 'Vision'
          : formatMatchMethod(method) || '—';

  const scoreValue = toNumber(score);
  if (scoreValue === null) return label;
  return `${label} (${scoreValue.toFixed(2)})`;
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    await copyToClipboard(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button
      onClick={handleCopy}
      title={`Copy ${label}`}
      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wider rounded border transition-colors bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-white active:scale-95"
    >
      <CopyIcon className="w-3 h-3" />
      {copied ? 'Copied!' : label}
    </button>
  );
}

type ArtifactTab = 'vision' | 'ocr' | 'frames';
type ScratchTool = 'OCR' | 'SEARCH' | 'VISION' | 'FINAL' | 'ERROR';
type ReasoningTermType = 'brand' | 'url' | 'evidence';
type ReasoningTerm = { text: string; type: ReasoningTermType };
type HighlightedReasoningPart = string | { text: string; type: ReasoningTermType };

const PIPELINE_STAGES = ['claim', 'ingest', 'frame_extract', 'ocr', 'vision', 'llm', 'persist', 'completed'] as const;
const AGENT_STAGES = ['claim', 'ingest', 'frame_extract', 'ocr', 'vision', 'llm', 'persist', 'completed'] as const;

function extractFrameTimestampKey(frame: { timestamp?: number | null; label?: string }): string | null {
  if (typeof frame.timestamp === 'number' && Number.isFinite(frame.timestamp)) {
    return frame.timestamp.toFixed(1);
  }
  if (typeof frame.label === 'string') {
    const match = frame.label.match(/([\d.]+)\s*s/i);
    if (match) {
      const parsed = Number.parseFloat(match[1]);
      if (Number.isFinite(parsed)) return parsed.toFixed(1);
    }
  }
  return null;
}

function formatStageName(stage: string): string {
  return stage.replace(/_/g, ' ');
}

function classifyReasoningTerm(term: string, brandText: string): ReasoningTerm {
  const cleanTerm = term.trim();
  const termLower = cleanTerm.toLowerCase();
  const brandLower = brandText.trim().toLowerCase();
  if (brandLower && termLower === brandLower) return { text: cleanTerm, type: 'brand' };
  if (/\.\w{2,4}$/i.test(cleanTerm)) return { text: cleanTerm, type: 'url' };
  return { text: cleanTerm, type: 'evidence' };
}

function reasoningPillClass(type: ReasoningTermType): string {
  if (type === 'brand') return 'bg-slate-700 text-white font-semibold px-2.5 py-1 rounded-full text-xs';
  if (type === 'url') return 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 px-2.5 py-1 rounded-full text-xs font-mono';
  return 'bg-amber-500/15 text-amber-300 border border-amber-500/30 px-2.5 py-1 rounded-full text-xs';
}

function reasoningInlineClass(type: ReasoningTermType): string {
  if (type === 'brand') return 'bg-slate-700/80 text-white font-semibold px-1 rounded';
  if (type === 'url') return 'bg-cyan-500/15 text-cyan-300 px-1 rounded font-mono';
  return 'bg-amber-500/15 text-amber-300 px-1 rounded';
}

function parseToolSegment(line: string): { tool: ScratchTool | null; query: string; finalFields: Record<string, string> } {
  const toolMatch = line.match(/\[TOOL:\s*(OCR|SEARCH|VISION|FINAL|ERROR)\b([^\]]*)\]/i);
  if (!toolMatch) return { tool: null, query: '', finalFields: {} };

  const tool = toolMatch[1].toUpperCase() as ScratchTool;
  const segment = toolMatch[0];
  const queryMatch = segment.match(/query\s*=\s*["']([^"']+)["']/i);

  const finalFields: Record<string, string> = {};
  if (tool === 'FINAL') {
    const quoted = /(\w+)\s*=\s*"([^"]*)"/g;
    let match = quoted.exec(segment);
    while (match) {
      finalFields[match[1].toLowerCase()] = match[2].trim();
      match = quoted.exec(segment);
    }
    const unquoted = /(\w+)\s*=\s*([^,\]\|]+)/g;
    match = unquoted.exec(segment);
    while (match) {
      const key = match[1].toLowerCase();
      if (!(key in finalFields)) finalFields[key] = match[2].trim();
      match = unquoted.exec(segment);
    }
  }

  return { tool, query: queryMatch?.[1]?.trim() || '', finalFields };
}

function toolTone(tool: ScratchTool | null): { icon: string; badge: string; border: string; text: string } {
  switch (tool) {
    case 'OCR':
      return { icon: '📝', badge: 'bg-cyan-500/10 border-cyan-500/30 text-cyan-300', border: 'border-cyan-500/50', text: 'text-cyan-300' };
    case 'SEARCH':
      return { icon: '🔍', badge: 'bg-amber-500/10 border-amber-500/30 text-amber-300', border: 'border-amber-500/50', text: 'text-amber-300' };
    case 'VISION':
      return { icon: '👁️', badge: 'bg-fuchsia-500/10 border-fuchsia-500/30 text-fuchsia-300', border: 'border-fuchsia-500/50', text: 'text-fuchsia-300' };
    case 'FINAL':
      return { icon: '✅', badge: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300', border: 'border-emerald-500/50', text: 'text-emerald-300' };
    case 'ERROR':
      return { icon: '❌', badge: 'bg-red-500/10 border-red-500/30 text-red-300', border: 'border-red-500/50', text: 'text-red-300' };
    default:
      return { icon: '•', badge: 'bg-slate-800 border-slate-700 text-slate-300', border: 'border-slate-700', text: 'text-slate-300' };
  }
}

function renderScratchboardEvent(event: string, index: number): ReactElement {
  const lines = event.split('\n');
  let currentTool: ScratchTool | null = null;
  const renderedLines: ReactElement[] = [];

  lines.forEach((rawLine, lineIndex) => {
    const trimmed = rawLine.trim();
    const key = `${index}-${lineIndex}`;

    if (!trimmed) {
      renderedLines.push(<div key={key} className="h-1" />);
      return;
    }

    if (/^---\s*Step\s+\d+\s*---/i.test(trimmed)) {
      renderedLines.push(
        <div key={key} className="text-slate-500 uppercase tracking-wider text-[10px] border-b border-slate-800 pb-1 mb-2 mt-4">
          {trimmed}
        </div>,
      );
      return;
    }

    if (trimmed.includes('✅ FINAL CONCLUSION')) {
      renderedLines.push(
        <div key={key} className="bg-emerald-500/10 border border-emerald-500/20 rounded px-3 py-2 text-emerald-300 font-semibold">
          {trimmed}
        </div>,
      );
      return;
    }

    if (/^🤔\s*Thought:/i.test(trimmed)) {
      renderedLines.push(
        <div key={key} className="italic text-slate-500">
          {trimmed}
        </div>,
      );
      return;
    }

    if (/^Action:/i.test(trimmed)) {
      const actionText = trimmed.replace(/^Action:\s*/i, '');
      const parsed = parseToolSegment(actionText);
      if (parsed.tool) currentTool = parsed.tool;
      const tone = toolTone(parsed.tool);
      const trailingText = actionText.replace(/\[TOOL:[^\]]+\]/i, '').trim();

      renderedLines.push(
        <div key={key} className="text-slate-300 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-200">Action:</span>
            {parsed.tool ? (
              <span className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${tone.badge}`}>
                <span>{tone.icon}</span>
                <span>{parsed.tool}</span>
              </span>
            ) : (
              <span className="text-slate-300">{actionText}</span>
            )}
            {trailingText && <span className="text-slate-400">{trailingText}</span>}
            {parsed.tool === 'SEARCH' && parsed.query && (
              <span className="bg-amber-500/10 text-amber-300 border border-amber-500/30 px-2 py-0.5 rounded text-[10px] font-mono">
                {parsed.query}
              </span>
            )}
          </div>
          {parsed.tool === 'FINAL' && Object.keys(parsed.finalFields).length > 0 && (
            <div className="ml-6 grid gap-1 text-[10px] text-emerald-200">
              {parsed.finalFields.brand && <div><span className="text-slate-500 uppercase mr-1">Brand:</span>{parsed.finalFields.brand}</div>}
              {parsed.finalFields.category && <div><span className="text-slate-500 uppercase mr-1">Category:</span>{parsed.finalFields.category}</div>}
              {parsed.finalFields.reason && <div><span className="text-slate-500 uppercase mr-1">Reason:</span>{parsed.finalFields.reason}</div>}
            </div>
          )}
        </div>,
      );
      return;
    }

    if (/^(Result:|Observation:)/i.test(trimmed)) {
      const parsed = parseToolSegment(trimmed);
      const tone = toolTone(parsed.tool || currentTool);
      renderedLines.push(
        <div key={key} className={`ml-2 pl-3 border-l-2 ${tone.border} text-slate-400 whitespace-pre-wrap`}>
          {trimmed}
        </div>,
      );
      return;
    }

    renderedLines.push(
      <div key={key} className="text-slate-300 whitespace-pre-wrap">
        {rawLine}
      </div>,
    );
  });

  return (
    <div className="border-b border-fuchsia-900/20 pb-2 mb-2 last:border-0">
      {renderedLines}
    </div>
  );
}

export function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<JobStatus | null>(null);
  const [result, setResult] = useState<ResultRow[] | null>(null);
  const [events, setEvents] = useState<string[]>([]);
  const [artifacts, setArtifacts] = useState<JobArtifacts | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');
  const [artifactTab, setArtifactTab] = useState<ArtifactTab>('vision');
  const [showAllReasoningTerms, setShowAllReasoningTerms] = useState(false);
  const [showFullReasoning, setShowFullReasoning] = useState(false);

  const scratchboardRef = useRef<HTMLDivElement>(null);
  const historyRef = useRef<HTMLDivElement>(null);
  const firstRow = result?.[0];
  const brandText = typeof firstRow?.Brand === 'string' ? firstRow.Brand.trim() : '';
  const reasoningRaw = firstRow
    ? (firstRow.Reasoning ?? (firstRow as any).reasoning ?? firstRow['Reasoning'])
    : '';
  const reasoningText = typeof reasoningRaw === 'string' ? reasoningRaw.trim() : '';
  const isRecoveredReasoning = reasoningText.toLowerCase().startsWith('(recovered)');
  const reasoningDisplayText = useMemo(() => {
    if (!reasoningText) return '';
    if (showFullReasoning || reasoningText.length <= 500) return reasoningText;
    return `${reasoningText.slice(0, 220).trimEnd()}...`;
  }, [reasoningText, showFullReasoning]);
  const quotedTermsAll = useMemo<ReasoningTerm[]>(() => {
    if (!reasoningText) return [];
    const regex = /'([^']+)'/g;
    const seen = new Set<string>();
    const orderedTerms: string[] = [];
    let match = regex.exec(reasoningText);
    while (match) {
      const clean = match[1].trim();
      const key = clean.toLowerCase();
      if (clean && !seen.has(key)) {
        seen.add(key);
        orderedTerms.push(clean);
      }
      match = regex.exec(reasoningText);
    }
    return orderedTerms.map((term) => classifyReasoningTerm(term, brandText));
  }, [reasoningText, brandText]);
  const visibleQuotedTerms = showAllReasoningTerms ? quotedTermsAll : quotedTermsAll.slice(0, 6);
  const hiddenQuotedTermsCount = Math.max(0, quotedTermsAll.length - visibleQuotedTerms.length);
  const highlightedReasoning = useMemo<HighlightedReasoningPart[]>(() => {
    if (!reasoningDisplayText) return [];
    if (quotedTermsAll.length === 0) return [reasoningDisplayText];
    const termType = new Map<string, ReasoningTermType>();
    quotedTermsAll.forEach((term) => termType.set(term.text.toLowerCase(), term.type));

    const parts: HighlightedReasoningPart[] = [];
    const regex = /'([^']+)'/g;
    let lastIndex = 0;
    let match = regex.exec(reasoningDisplayText);
    while (match) {
      if (match.index > lastIndex) {
        parts.push(reasoningDisplayText.slice(lastIndex, match.index));
      }
      const term = match[1];
      parts.push({ text: `'${term}'`, type: termType.get(term.toLowerCase()) || 'evidence' });
      lastIndex = regex.lastIndex;
      match = regex.exec(reasoningDisplayText);
    }
    if (lastIndex < reasoningDisplayText.length) {
      parts.push(reasoningDisplayText.slice(lastIndex));
    }
    return parts;
  }, [reasoningDisplayText, quotedTermsAll]);
  const ocrText = artifacts?.ocr_text?.text || '';
  const agentScratchboardEvents = useMemo(
    () => events
      .filter((evt) => evt.includes(' agent:\n') || evt.includes(' agent: '))
      .map((evt) => {
        if (evt.includes(' agent:\n')) return evt.split(' agent:\n')[1] ?? evt;
        if (evt.includes(' agent: ')) return evt.split(' agent: ')[1] ?? evt;
        return evt;
      }),
    [events],
  );
  const ocrByTimestamp = useMemo(() => {
    const map = new Map<string, string>();
    for (const line of (ocrText || '').split('\n')) {
      const match = line.match(/^\[([\d.]+)s\]\s*(.*)$/);
      if (!match) continue;
      const ts = Number.parseFloat(match[1]);
      if (!Number.isFinite(ts)) continue;
      map.set(ts.toFixed(1), match[2] || '');
    }
    return map;
  }, [ocrText]);

  useEffect(() => {
    setShowAllReasoningTerms(false);
    setShowFullReasoning(false);
  }, [reasoningText]);

  useEffect(() => {
    if (scratchboardRef.current) {
      scratchboardRef.current.scrollTop = scratchboardRef.current.scrollHeight;
    }
    if (historyRef.current) {
      historyRef.current.scrollTop = historyRef.current.scrollHeight;
    }
  }, [events]);

  useEffect(() => {
    let unmounted = false;
    if (!id) return;

    const poll = async () => {
      try {
        const j = await getJob(id);
        if (unmounted) return;
        setJob(j);
        setError('');

        if (j.status === 'completed' || j.status === 'failed') {
          try {
            const r = await getJobResult(id);
            if (r.result && !unmounted) setResult(r.result);
          } catch {
            // no-op
          }
        }

        try {
          const a = await getJobArtifacts(id);
          if (!unmounted) setArtifacts(a.artifacts || null);
        } catch {
          // no-op
        }

        if (j.status === 'processing' || j.status === 'completed' || j.status === 'failed') {
          try {
            const e = await getJobEvents(id);
            if (e.events && !unmounted) setEvents(e.events);
          } catch {
            // no-op
          }
        }

        if (!unmounted && j.status !== 'completed' && j.status !== 'failed') {
          setTimeout(poll, 1500);
        }
      } catch (err: any) {
        if (!unmounted) {
          setError(err.message || 'Failed to load job');
          setLoading(false);
        }
      } finally {
        if (!unmounted) setLoading(false);
      }
    };
    poll();
    return () => { unmounted = true; };
  }, [id]);

  const handleExportCSV = useCallback(() => {
    if (result) exportResultsCSV(result, `job-${id}-results.csv`);
  }, [result, id]);

  if (loading && !job) {
    return <div className="p-8 text-slate-400 flex items-center gap-2 animate-pulse">Loading job…</div>;
  }

  if (error && !job) {
    return (
      <div className="p-8 text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg max-w-xl mx-auto flex flex-col items-center py-12">
        <ExclamationTriangleIcon className="w-12 h-12 mb-4" />
        <h2 className="text-xl font-bold mb-2">Could Not Load Job</h2>
        <p className="text-red-300 mb-6 text-sm text-center">{error}</p>
        <Link to="/jobs" className="text-sm text-slate-300 bg-slate-800 hover:bg-slate-700 px-4 py-2 rounded transition-colors flex items-center gap-2">
          <ArrowLeftIcon /> Back to Jobs
        </Link>
      </div>
    );
  }

  if (!job) return null;

  const progressPercent = Math.round(job.progress ?? 0);

  const frameItems = artifacts?.latest_frames || [];
  const visionBoard = artifacts?.vision_board;
  const frameCount = frameItems.length;
  const stages = job.mode === 'agent' ? AGENT_STAGES : PIPELINE_STAGES;
  const currentStage = (job.stage || '').trim();
  const currentIdx = stages.indexOf(currentStage as (typeof stages)[number]);

  const categoryText = typeof firstRow?.Category === 'string' ? firstRow.Category.trim() : '';
  const categoryIdRaw = firstRow?.['Category ID'] ?? (firstRow as any)?.category_id;
  const categoryIdText = typeof categoryIdRaw === 'string' ? categoryIdRaw.trim() : String(categoryIdRaw ?? '').trim();

  const confidenceValue = toNumber(firstRow?.Confidence);
  const confidenceDisplay = confidenceValue === null ? 'N/A' : confidenceValue.toFixed(2);
  const confidencePercent = confidenceValue === null
    ? 0
    : Math.max(0, Math.min(100, confidenceValue * 100));
  const confidenceGradient = confidenceValue === null
    ? 'from-slate-500 to-slate-400'
    : confidenceValue >= 0.8
      ? 'from-emerald-500 to-emerald-400'
      : confidenceValue >= 0.5
        ? 'from-amber-500 to-amber-400'
        : 'from-red-500 to-red-400';
  const confidenceSummaryDisplay = confidenceValue === null ? '—' : confidenceValue.toFixed(2);
  const confidenceSummaryTextColor = confidenceValue === null
    ? 'text-slate-500'
    : confidenceValue >= 0.8
      ? 'text-emerald-400'
      : confidenceValue >= 0.5
        ? 'text-amber-400'
        : 'text-red-400';
  const confidenceSummaryDotColor = confidenceValue === null
    ? 'bg-slate-500'
    : confidenceValue >= 0.8
      ? 'bg-emerald-400'
      : confidenceValue >= 0.5
        ? 'bg-amber-400'
        : 'bg-red-400';

  const matchMethodRaw = firstRow ? (firstRow as any).category_match_method : '';
  const matchMethodLabel = formatMatchMethod(matchMethodRaw);
  const matchScoreValue = toNumber(firstRow ? (firstRow as any).category_match_score : null);
  const matchMethodText = matchMethodLabel
    ? matchScoreValue === null
      ? `${matchMethodLabel} Match`
      : `${matchMethodLabel} Match (${matchScoreValue.toFixed(2)})`
    : '';
  const summaryMatchDisplay = formatSummaryMatch(
    matchMethodRaw,
    firstRow ? (firstRow as any).category_match_score : null,
  );
  const summaryFrameDisplay = artifacts ? String(frameCount) : '—';

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-24 animate-in fade-in duration-500">
      <div className="flex items-center gap-4 text-sm text-slate-400 mb-2">
        <Link to="/jobs" className="hover:text-primary-400 flex items-center gap-1 transition-colors">
          <ArrowLeftIcon /> Jobs
        </Link>
        <span>/</span>
        <span className="font-mono text-slate-300 truncate max-w-sm">{job.job_id}</span>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-sm flex flex-col gap-6 relative overflow-hidden">
        <div className="absolute top-0 left-0 w-full h-1 bg-slate-800">
          <div className="h-full bg-gradient-to-r from-emerald-400 to-cyan-400 transition-all duration-1000 ease-in-out" style={{ width: `${progressPercent}%` }} />
        </div>

        <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
                {job.mode === 'agent' ? <MagicWandIcon className="text-fuchsia-400" /> : <FileTextIcon className="text-cyan-400" />}
                {job.mode.charAt(0).toUpperCase() + job.mode.slice(1)} Job
              </h1>
              <span className={`px-2.5 py-1 rounded-md text-xs font-semibold uppercase tracking-wider border backdrop-blur-md ${
                job.status === 'completed' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                job.status === 'failed' ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                job.status === 'processing' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                'bg-amber-500/10 text-amber-400 border-amber-500/20'
              }`}>
                {job.status} {job.status === 'processing' && `${progressPercent}%`}
              </span>
            </div>

            <div className="flex flex-wrap gap-2">
              <CopyButton text={job.job_id} label="Copy Job ID" />
              {result && (
                <>
                  <CopyButton text={JSON.stringify(result, null, 2)} label="Copy JSON" />
                  <button onClick={handleExportCSV} className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wider rounded border transition-colors bg-emerald-900/40 border-emerald-700/50 text-emerald-300 hover:bg-emerald-800/60 active:scale-95">
                    <DownloadIcon className="w-3 h-3" /> Export CSV
                  </button>
                </>
              )}
            </div>

            <div className="text-sm text-slate-400 break-all max-w-3xl font-mono opacity-80 bg-slate-950/50 p-2 rounded border border-slate-800">{job.url}</div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              <div className="bg-slate-950/70 border border-slate-800 rounded p-3">
                <div className="uppercase tracking-wider text-slate-500 mb-1">Current Stage</div>
                <div className="text-slate-200 font-mono">{job.stage || 'unknown'}</div>
              </div>
              <div className="bg-slate-950/70 border border-slate-800 rounded p-3">
                <div className="uppercase tracking-wider text-slate-500 mb-1">Stage Detail</div>
                <div className="text-slate-300">{job.stage_detail || '—'}</div>
              </div>
            </div>
          </div>

          <div className="flex flex-col items-end gap-1 text-sm text-slate-500 shrink-0">
            <span className="flex items-center gap-2 bg-slate-950 px-3 py-1.5 rounded-md border border-slate-800 shadow-sm">Created: <span className="text-slate-300 font-mono text-xs">{job.created_at}</span></span>
            <span className="flex items-center gap-2 bg-slate-950 px-3 py-1.5 rounded-md border border-slate-800 shadow-sm">Updated: <span className="text-slate-300 font-mono text-xs">{job.updated_at}</span></span>
          </div>
        </div>

        {job.error && (
          <div className="bg-red-500/10 border border-red-500/20 text-red-400 p-4 rounded-lg text-sm shadow-inner flex flex-col gap-2">
            <div className="flex items-center gap-2 font-bold"><ExclamationTriangleIcon /> Execution Failure</div>
            <pre className="font-mono text-xs whitespace-pre-wrap px-2 opacity-80">{job.error}</pre>
          </div>
        )}
      </div>

      {job.status === 'completed' && firstRow && firstRow.Brand !== 'Err' && (
        <div className="bg-slate-900 border border-emerald-500/20 border-t-2 border-t-emerald-500/50 rounded-xl px-4 md:px-6 py-3 flex flex-col md:flex-row items-start md:items-center justify-between gap-3 md:gap-0">
          <div className="flex items-center gap-3 min-w-0">
            <CheckCircledIcon className="w-5 h-5 text-emerald-400 shrink-0" />
            <span
              title={brandText || 'Unknown Brand'}
              className="text-base md:text-lg font-bold text-white max-w-[14rem] md:max-w-xs truncate"
            >
              {brandText || 'Unknown Brand'}
            </span>
            <span className="text-slate-600 shrink-0">→</span>
            <span
              title={categoryText || 'Unknown Category'}
              className="text-base md:text-lg font-bold text-emerald-400 max-w-[14rem] md:max-w-sm truncate"
            >
              {categoryText || 'Unknown Category'}
            </span>
            {categoryIdText && (
              <span className="text-[10px] font-mono text-slate-500 bg-slate-800 px-2 py-0.5 rounded shrink-0">
                ID: {categoryIdText}
              </span>
            )}
          </div>

          <div className="flex items-stretch self-stretch md:self-auto shrink-0">
            <div className="px-3 md:px-4 border-l border-slate-700/50 text-center">
              <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">Confidence</div>
              <div className={`inline-flex items-center justify-center gap-1 text-sm font-bold ${confidenceSummaryTextColor}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${confidenceSummaryDotColor}`} aria-hidden />
                <span>{confidenceSummaryDisplay}</span>
              </div>
            </div>
            <div className="px-3 md:px-4 border-l border-slate-700/50 text-center">
              <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">Match</div>
              <div className="text-sm font-mono text-cyan-400">{summaryMatchDisplay}</div>
            </div>
            <div className="px-3 md:px-4 border-l border-slate-700/50 text-center">
              <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">Frames</div>
              <div className="text-sm font-mono text-slate-300">{summaryFrameDisplay}</div>
            </div>
          </div>
        </div>
      )}

      {firstRow && firstRow.Brand !== 'Err' && (
        <div className="grid gap-6 animate-in slide-in-from-bottom-4 duration-500 fill-mode-forwards">
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <CheckCircledIcon className="text-emerald-400" /> Final Classification
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl shadow-sm">
              <div className="text-xs uppercase text-slate-500 font-bold tracking-wider mb-2">Category</div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="text-2xl font-bold bg-gradient-to-r from-emerald-400 to-emerald-200 bg-clip-text text-transparent">
                  {categoryText || 'None'}
                </div>
                {categoryIdText && (
                  <span className="text-xs font-mono text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded ml-2">
                    ID: {categoryIdText}
                  </span>
                )}
              </div>
              {matchMethodText && (
                <div className="mt-2 text-[10px] uppercase tracking-wider text-slate-500">
                  {matchMethodText}
                </div>
              )}
            </div>
            <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl shadow-sm">
              <div className="text-xs uppercase text-slate-500 font-bold tracking-wider mb-2">Brand Detected</div>
              <div className="text-2xl font-bold text-white drop-shadow-sm">{brandText || 'N/A'}</div>
            </div>
            <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl shadow-sm">
              <div className="text-xs uppercase text-slate-500 font-bold tracking-wider mb-2">Confidence Score</div>
              <div className="text-2xl font-bold text-cyan-400 drop-shadow-sm">{confidenceDisplay}</div>
              <div className="mt-3 h-2 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={`h-full rounded-full bg-gradient-to-r ${confidenceGradient} transition-all duration-500`}
                  style={{ width: `${confidencePercent}%` }}
                />
              </div>
            </div>
          </div>
          <div className="bg-gradient-to-r from-slate-900 to-slate-900/80 border border-slate-800 border-l-[3px] border-l-emerald-500/50 rounded-xl p-6">
            <div className="flex items-center justify-between gap-3 mb-3">
              <h3 className="text-xs uppercase tracking-wider text-slate-500 font-bold">💡 LLM Reasoning</h3>
              <CopyButton text={reasoningText || 'No reasoning provided by the LLM.'} label="Copy Reasoning" />
            </div>

            {isRecoveredReasoning && (
              <div className="mb-3 inline-flex items-center gap-1 text-amber-300 border border-amber-500/30 bg-amber-500/10 rounded px-2 py-1 text-xs">
                <span>🔍</span>
                <span>Web-assisted recovery</span>
              </div>
            )}

            {visibleQuotedTerms.length > 0 && (
              <div className="mb-4">
                <div className="flex flex-wrap gap-2">
                  {visibleQuotedTerms.map((term, idx) => (
                    <span
                      key={`${term.text}-${idx}`}
                      role="status"
                      className={reasoningPillClass(term.type)}
                    >
                      {term.text}
                    </span>
                  ))}
                  {hiddenQuotedTermsCount > 0 && !showAllReasoningTerms && (
                    <button
                      type="button"
                      onClick={() => setShowAllReasoningTerms(true)}
                      className="px-2.5 py-1 rounded-full text-xs border border-slate-700 text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors"
                    >
                      +{hiddenQuotedTermsCount} more
                    </button>
                  )}
                  {quotedTermsAll.length > 6 && showAllReasoningTerms && (
                    <button
                      type="button"
                      onClick={() => setShowAllReasoningTerms(false)}
                      className="px-2.5 py-1 rounded-full text-xs border border-slate-700 text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors"
                    >
                      Show less
                    </button>
                  )}
                </div>
                <div className="border-b border-slate-800 mt-4" />
              </div>
            )}

            {reasoningText ? (
              <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">
                {highlightedReasoning.map((part, idx) => (
                  typeof part === 'string' ? (
                    <span key={idx}>{part}</span>
                  ) : (
                    <span key={idx} className={reasoningInlineClass(part.type)}>
                      {part.text}
                    </span>
                  )
                ))}
              </p>
            ) : (
              <p className="text-slate-600 italic text-sm">No reasoning provided by the LLM.</p>
            )}

            {reasoningText.length > 500 && (
              <button
                type="button"
                onClick={() => setShowFullReasoning((current) => !current)}
                className="mt-3 text-xs text-cyan-300 hover:text-cyan-200 underline underline-offset-2"
              >
                {showFullReasoning ? 'Show less' : 'Show more'}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="bg-slate-900 border border-slate-800 rounded-xl shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800 bg-slate-900/70">
          <button type="button" onClick={() => setArtifactTab('vision')} className={`px-3 py-1.5 text-xs rounded border ${artifactTab === 'vision' ? 'bg-primary-600 border-primary-500 text-white' : 'bg-slate-950 border-slate-800 text-slate-300'}`}>Vision Board</button>
          <button type="button" onClick={() => setArtifactTab('ocr')} className={`px-3 py-1.5 text-xs rounded border ${artifactTab === 'ocr' ? 'bg-primary-600 border-primary-500 text-white' : 'bg-slate-950 border-slate-800 text-slate-300'}`}>OCR Output</button>
          <button type="button" onClick={() => setArtifactTab('frames')} className={`px-3 py-1.5 text-xs rounded border ${artifactTab === 'frames' ? 'bg-primary-600 border-primary-500 text-white' : 'bg-slate-950 border-slate-800 text-slate-300'}`}>Latest Frames</button>
        </div>

        {artifactTab === 'vision' && (
          <div className="p-4 space-y-4">
            {visionBoard?.image_url && <img src={toApiUrl(visionBoard.image_url)} alt="Vision board" className="max-h-96 rounded border border-slate-700" />}
            {visionBoard?.plot_url && (
              <a href={toApiUrl(visionBoard.plot_url)} target="_blank" rel="noreferrer" className="text-xs text-primary-300 underline">Open vision board metadata</a>
            )}
            {(visionBoard?.top_matches || []).length > 0 ? (
              <div className="grid gap-2">
                {(visionBoard?.top_matches || []).map((m, idx) => (
                  <div key={idx} className="flex items-center justify-between text-xs bg-slate-950 border border-slate-800 rounded px-3 py-2">
                    <span className="text-slate-200">{m.label}</span>
                    <span className="font-mono text-cyan-300">{Number(m.score).toFixed(4)}</span>
                  </div>
                ))}
              </div>
            ) : <div className="text-xs text-slate-500">No vision board matches available.</div>}
          </div>
        )}

        {artifactTab === 'ocr' && (
          <div className="p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-xs text-slate-500">OCR output</div>
              <CopyButton text={ocrText} label="Copy OCR" />
            </div>
            <div className="max-h-80 overflow-auto text-xs font-mono whitespace-pre-wrap text-slate-300 bg-slate-950 border border-slate-800 rounded p-3">
              {ocrText || 'No OCR text available.'}
            </div>
          </div>
        )}

        {artifactTab === 'frames' && (
          <div className="p-4">
            {frameItems.length > 0 ? (
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                {frameItems.map((frame, idx) => {
                  const frameLabel = frame.label || (typeof frame.timestamp === 'number' ? `${frame.timestamp.toFixed(1)}s` : `Frame ${idx + 1}`);
                  const frameTsKey = extractFrameTimestampKey(frame);
                  const frameOcrText = frameTsKey ? ocrByTimestamp.get(frameTsKey) : '';
                  return (
                    <div key={idx} className="aspect-video bg-slate-950 rounded border border-slate-800 overflow-hidden relative group">
                      <img src={toApiUrl(frame.url)} alt={frameLabel} className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-300" />
                      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 to-transparent p-2 text-[10px] font-mono text-emerald-400">
                        {frameLabel}
                      </div>
                      {frameOcrText && (
                        <div className="absolute inset-0 bg-black/85 opacity-0 group-hover:opacity-100 transition-opacity duration-200 p-3 flex items-center justify-center">
                          <p className="text-[10px] text-cyan-300 font-mono leading-relaxed text-center line-clamp-6">
                            {frameOcrText}
                          </p>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : <div className="text-xs text-slate-500">No latest frames available.</div>}
          </div>
        )}
      </div>

      {job.mode === 'agent' && agentScratchboardEvents.length > 0 && (
        <div className="bg-slate-950 border border-fuchsia-900/40 rounded-xl overflow-hidden shadow-inner flex flex-col animate-in slide-in-from-bottom-4 duration-500 delay-100 fill-mode-forwards">
          <div className="bg-slate-900/80 px-4 py-3 border-b border-fuchsia-900/40 font-semibold text-fuchsia-200 flex items-center gap-2">
            <MagicWandIcon className="text-fuchsia-400" /> Agent Scratchboard
          </div>
          <div className="p-4 h-96 overflow-y-auto space-y-2 font-mono text-xs text-slate-300" ref={scratchboardRef}>
            {agentScratchboardEvents.map((evt, i) => (
              <Fragment key={i}>{renderScratchboardEvent(evt, i)}</Fragment>
            ))}
          </div>
        </div>
      )}

      {(events.length > 0 || job.stage) && (
        <div className="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden shadow-inner flex flex-col animate-in slide-in-from-bottom-4 duration-500 delay-100 fill-mode-forwards">
          <div className="px-4 py-4 border-b border-slate-800 bg-slate-900/60 overflow-x-auto">
            <div className="min-w-[680px] flex items-center gap-0 w-full px-1 pb-5">
              {stages.map((stage, idx) => {
                const isDone = job.status === 'completed' || currentIdx > idx || (job.status === 'failed' && currentIdx > idx);
                const isCurrent = job.status === 'processing' && currentIdx === idx;
                const isFailed = job.status === 'failed' && currentIdx === idx;
                const stageLabel = formatStageName(stage);
                const dotTitle = isCurrent && job.stage_detail ? `${stageLabel}: ${job.stage_detail}` : stageLabel;
                return (
                  <Fragment key={stage}>
                    {idx > 0 && (
                      <div
                        className={`flex-1 h-0.5 ${isDone ? 'bg-emerald-500' : isFailed ? 'bg-red-500' : 'bg-slate-800'}`}
                      />
                    )}
                    <div className="relative shrink-0 flex flex-col items-center gap-1">
                      <div
                        title={dotTitle}
                        className={`w-3 h-3 rounded-full border-2 ${
                          isDone
                            ? 'bg-emerald-500 border-emerald-400'
                            : isCurrent
                              ? 'bg-blue-500 border-blue-400 animate-pulse'
                              : isFailed
                                ? 'bg-red-500 border-red-400'
                                : 'bg-slate-800 border-slate-700'
                        }`}
                      />
                      <span
                        className={`text-[9px] uppercase tracking-wider absolute -bottom-5 whitespace-nowrap ${
                          isDone
                            ? 'text-emerald-500'
                            : isCurrent
                              ? 'text-blue-400'
                              : isFailed
                                ? 'text-red-400'
                                : 'text-slate-600'
                        }`}
                      >
                        {stageLabel}
                      </span>
                    </div>
                  </Fragment>
                );
              })}
            </div>
          </div>
          <div className="bg-slate-900/80 px-4 py-3 border-b border-slate-800 font-semibold text-slate-300 flex items-center gap-2">
            <MagicWandIcon className="text-fuchsia-400" /> Stage / Event History
          </div>
          {events.length > 0 ? (
            <div className="p-4 h-96 overflow-y-auto space-y-2 font-mono text-xs text-slate-400" ref={historyRef}>
              {events.map((evt, i) => (
                <div key={i} className="border-b border-slate-800/50 pb-2 mb-2 last:border-0 whitespace-pre-wrap">{evt}</div>
              ))}
            </div>
          ) : (
            <div className="p-4 text-xs text-slate-500">No events yet.</div>
          )}
        </div>
      )}

      <details className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden cursor-pointer shadow-sm group">
        <summary className="px-6 py-4 font-semibold text-slate-400 group-hover:bg-slate-800/50 transition-colors list-none flex items-center gap-2">
          <DownloadIcon /> Raw JSON Context
        </summary>
        <div className="p-6 bg-slate-950 border-t border-slate-800 font-mono text-xs text-emerald-400/70 overflow-x-auto">
          <pre>{JSON.stringify({ settings: job.settings, result, artifacts }, null, 2)}</pre>
        </div>
      </details>
    </div>
  );
}
