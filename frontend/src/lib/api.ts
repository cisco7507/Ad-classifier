/**
 * frontend/src/lib/api.ts
 * Extended API client with typed error handling + CSV export helper.
 */

import axios, { AxiosError } from 'axios';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const api = axios.create({ baseURL: API_BASE_URL, timeout: 15000 });

// ── Types ────────────────────────────────────────────────────────────────────

export interface ClusterNode {
  nodes:  Record<string, string>;
  status: Record<string, boolean>;
  self:   string;
}

export interface JobSettings {
  categories:    string;
  provider:      string;
  model_name:    string;
  ocr_engine:    string;
  ocr_mode:      string;
  scan_mode:     string;
  override:      boolean;
  enable_search: boolean;
  enable_web_search?: boolean;
  enable_agentic_search?: boolean;
  enable_vision: boolean;
  context_size:  number;
}

export interface JobStatus {
  job_id:     string;
  status:     string;
  stage?:     string;
  stage_detail?: string;
  duration_seconds?: number | null;
  created_at: string;
  updated_at: string;
  progress:   number;
  error?:     string;
  settings?:  JobSettings;
  mode:       string;
  url:        string;
  brand?:     string;
  category?:  string;
  category_id?: string;
}

export interface ArtifactFrame {
  timestamp?: number | null;
  label?: string;
  url: string;
}

export interface ArtifactOCR {
  text?: string;
  lines?: string[];
  url?: string | null;
}

export interface ArtifactVisionMatch {
  label: string;
  score: number;
}

export interface ArtifactVisionBoard {
  image_url?: string | null;
  plot_url?: string | null;
  top_matches?: ArtifactVisionMatch[];
  metadata?: Record<string, unknown>;
}

export interface PerFrameVision {
  frame_index: number;
  top_category: string;
  top_score: number;
}

export interface JobArtifacts {
  latest_frames: ArtifactFrame[];
  per_frame_vision: PerFrameVision[];
  ocr_text: ArtifactOCR;
  vision_board: ArtifactVisionBoard;
  extras?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface OllamaModel {
  name: string;
  size?: number;
  modified_at?: string;
}

export interface ResultRow {
  Brand:       string;
  Category:    string;
  'Category ID': string;
  Confidence:  number;
  Reasoning:   string;
  [key: string]: unknown;
}

export interface Metrics {
  jobs_queued:               number;
  jobs_processing:           number;
  jobs_completed:            number;
  jobs_failed:               number;
  jobs_submitted_this_process: number;
  uptime_seconds:            number;
  node:                      string;
}

export interface AnalyticsData {
  top_brands: { brand: string; count: number }[];
  categories: { category: string; count: number }[];
  avg_duration_by_mode: { mode: string; avg_duration: number | null; count: number }[];
  avg_duration_by_scan: { scan_mode: string; avg_duration: number | null; count: number }[];
  daily_outcomes: { day: string; status: string; count: number }[];
  providers: { provider: string; count: number }[];
  totals: {
    total: number;
    completed: number;
    failed: number;
    avg_duration: number | null;
  };
}

export function emptyAnalytics(): AnalyticsData {
  return {
    top_brands: [],
    categories: [],
    avg_duration_by_mode: [],
    avg_duration_by_scan: [],
    daily_outcomes: [],
    providers: [],
    totals: {
      total: 0,
      completed: 0,
      failed: 0,
      avg_duration: null,
    },
  };
}

function mergeAnalytics(responses: AnalyticsData[]): AnalyticsData {
  if (responses.length === 0) return emptyAnalytics();
  if (responses.length === 1) return responses[0];

  const mergeCounts = (
    key: 'brand' | 'category' | 'provider',
    arrays: Array<Array<Record<string, string | number | null>>>,
  ): Array<{ key: string; count: number }> => {
    const map = new Map<string, number>();
    for (const arr of arrays) {
      for (const item of arr) {
        const label = String(item[key] ?? '').trim();
        if (!label) continue;
        const count = Number(item.count ?? 0);
        map.set(label, (map.get(label) || 0) + count);
      }
    }
    return Array.from(map.entries())
      .map(([label, count]) => ({ key: label, count }))
      .sort((a, b) => b.count - a.count);
  };

  const mergeWeightedAvg = (
    key: 'mode' | 'scan_mode',
    arrays: Array<Array<Record<string, string | number | null>>>,
  ): Array<{ key: string; avg_duration: number | null; count: number }> => {
    const map = new Map<string, { totalDuration: number; totalCount: number }>();
    for (const arr of arrays) {
      for (const item of arr) {
        const label = String(item[key] ?? '').trim();
        if (!label) continue;
        const count = Number(item.count ?? 0);
        const avg = Number(item.avg_duration ?? 0);
        if (!Number.isFinite(count) || count <= 0) continue;
        if (!Number.isFinite(avg)) continue;
        const existing = map.get(label) || { totalDuration: 0, totalCount: 0 };
        existing.totalDuration += avg * count;
        existing.totalCount += count;
        map.set(label, existing);
      }
    }

    return Array.from(map.entries())
      .map(([label, value]) => ({
        key: label,
        avg_duration:
          value.totalCount > 0
            ? Math.round((value.totalDuration / value.totalCount) * 10) / 10
            : null,
        count: value.totalCount,
      }))
      .sort((a, b) => b.count - a.count);
  };

  const dailyMap = new Map<string, number>();
  for (const response of responses) {
    for (const row of response.daily_outcomes) {
      const key = `${row.day}|${row.status}`;
      dailyMap.set(key, (dailyMap.get(key) || 0) + row.count);
    }
  }
  const daily_outcomes = Array.from(dailyMap.entries())
    .map(([key, count]) => {
      const [day, status] = key.split('|');
      return { day, status, count };
    })
    .sort((a, b) => a.day.localeCompare(b.day));

  let total = 0;
  let completed = 0;
  let failed = 0;
  let weightedDurationSum = 0;
  let weightedDurationCount = 0;

  for (const response of responses) {
    total += response.totals.total || 0;
    completed += response.totals.completed || 0;
    failed += response.totals.failed || 0;
    if (response.totals.avg_duration != null && response.totals.completed > 0) {
      weightedDurationSum += response.totals.avg_duration * response.totals.completed;
      weightedDurationCount += response.totals.completed;
    }
  }

  return {
    top_brands: mergeCounts(
      'brand',
      responses.map((r) => r.top_brands),
    )
      .map((row) => ({ brand: row.key, count: row.count }))
      .slice(0, 20),
    categories: mergeCounts(
      'category',
      responses.map((r) => r.categories),
    )
      .map((row) => ({ category: row.key, count: row.count }))
      .slice(0, 25),
    avg_duration_by_mode: mergeWeightedAvg(
      'mode',
      responses.map((r) => r.avg_duration_by_mode),
    ).map((row) => ({ mode: row.key, avg_duration: row.avg_duration, count: row.count })),
    avg_duration_by_scan: mergeWeightedAvg(
      'scan_mode',
      responses.map((r) => r.avg_duration_by_scan),
    ).map((row) => ({ scan_mode: row.key, avg_duration: row.avg_duration, count: row.count })),
    daily_outcomes,
    providers: mergeCounts(
      'provider',
      responses.map((r) => r.providers),
    ).map((row) => ({ provider: row.key, count: row.count })),
    totals: {
      total,
      completed,
      failed,
      avg_duration:
        weightedDurationCount > 0
          ? Math.round((weightedDurationSum / weightedDurationCount) * 10) / 10
          : null,
    },
  };
}

// ── API helpers with typed errors ─────────────────────────────────────────────

function parseError(err: unknown): string {
  if (err instanceof AxiosError) {
    if (!err.response) return `Network error — cannot reach ${API_BASE_URL}`;
    const detail = err.response.data?.detail;
    return detail ? String(detail) : `HTTP ${err.response.status}: ${err.response.statusText}`;
  }
  return String(err);
}

async function safe<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (err) {
    throw new Error(parseError(err));
  }
}

// ── Exported API functions ───────────────────────────────────────────────────

export const getClusterNodes  = () => safe(() => api.get<ClusterNode>('/cluster/nodes').then(r => r.data));
export const getClusterJobs   = () => safe(() => api.get<JobStatus[]>('/cluster/jobs').then(r => r.data));
export const getMetrics       = () => safe(() => api.get<Metrics>('/metrics').then(r => r.data));
export const getAnalytics     = () => safe(() => api.get<AnalyticsData>('/analytics').then(r => r.data));
export const getJob           = (id: string) => safe(() => api.get<JobStatus>(`/jobs/${id}`).then(r => r.data));
export const getJobResult     = (id: string) => safe(() => api.get<{ result: ResultRow[] | null }>(`/jobs/${id}/result`).then(r => r.data));
export const getJobArtifacts  = (id: string) => safe(() => api.get<{ artifacts: JobArtifacts }>(`/jobs/${id}/artifacts`).then(r => r.data));
export const getJobEvents     = (id: string) => safe(() => api.get<{ events: string[] }>(`/jobs/${id}/events`).then(r => r.data));
export const getOllamaModels  = () => safe(() => api.get<OllamaModel[]>('/ollama/models').then(r => r.data));
export const deleteJob        = (id: string) => safe(() => api.delete(`/jobs/${id}`).then(r => r.data));
export const deleteJobsBulk   = async (jobIds: string[]) => {
  const results = await Promise.allSettled(jobIds.map((id) => deleteJob(id)));
  const deleted = results.filter((result) => result.status === 'fulfilled').length;
  const failed = results.length - deleted;
  return { status: 'deleted', requested: jobIds.length, deleted, failed };
};
export const submitUrls       = (data: unknown) => safe(() => api.post('/jobs/by-urls', data).then(r => r.data));
export const submitFilePath   = (data: unknown) => safe(() => api.post('/jobs/by-filepath', data).then(r => r.data));
export const submitFolderPath = (data: unknown) => safe(() => api.post('/jobs/by-folder', data).then(r => r.data));
export const getJobVideoUrl   = (jobId: string): string => `${API_BASE_URL}/jobs/${jobId}/video`;

export async function getClusterAnalytics(): Promise<AnalyticsData> {
  const cluster = await getClusterNodes();
  const nodeUrls = Object.values(cluster.nodes || {});
  if (nodeUrls.length === 0) return emptyAnalytics();

  const responses = await Promise.allSettled(
    nodeUrls.map(async (url) => {
      const target = `${String(url).replace(/\/$/, '')}/analytics`;
      const res = await fetch(target);
      if (!res.ok) throw new Error(`analytics fetch failed: ${res.status}`);
      return (await res.json()) as AnalyticsData;
    }),
  );

  const successful = responses
    .filter((row): row is PromiseFulfilledResult<AnalyticsData> => row.status === 'fulfilled')
    .map((row) => row.value);

  return mergeAnalytics(successful);
}

// ── CSV export ───────────────────────────────────────────────────────────────

/**
 * Convert an array of result rows to a CSV string and trigger a browser download.
 */
export function exportResultsCSV(rows: ResultRow[], filename = 'results.csv'): void {
  if (!rows.length) return;

  const cols: (keyof ResultRow)[] = ['Brand', 'Category', 'Category ID', 'Confidence', 'Reasoning'];
  const header = cols.map(c => `"${String(c)}"`).join(',');
  const body   = rows.map(row =>
    cols.map(c => `"${String(row[c] ?? '').replace(/"/g, '""')}"`).join(',')
  ).join('\n');

  const blob = new Blob([header + '\n' + body], { type: 'text/csv;charset=utf-8;' });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement('a'), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

// ── Copy helpers ─────────────────────────────────────────────────────────────

export async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
  } else {
    // Fallback for http contexts
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
}
