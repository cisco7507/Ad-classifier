/**
 * frontend/src/lib/api.ts
 * Extended API client with typed error handling + CSV export helper.
 */

import axios, { AxiosError } from 'axios';

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const api = axios.create({ baseURL, timeout: 15000 });

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

export interface JobArtifacts {
  latest_frames: ArtifactFrame[];
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

// ── API helpers with typed errors ─────────────────────────────────────────────

function parseError(err: unknown): string {
  if (err instanceof AxiosError) {
    if (!err.response) return `Network error — cannot reach ${baseURL}`;
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
