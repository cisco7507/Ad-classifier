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
  enable_vision: boolean;
  context_size:  number;
  workers:       number;
}

export interface JobStatus {
  job_id:     string;
  status:     string;
  created_at: string;
  updated_at: string;
  progress:   number;
  error?:     string;
  settings?:  JobSettings;
  mode:       string;
  url:        string;
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
export const getJobArtifacts  = (id: string) => safe(() => api.get(`/jobs/${id}/artifacts`).then(r => r.data));
export const getJobEvents     = (id: string) => safe(() => api.get<{ events: string[] }>(`/jobs/${id}/events`).then(r => r.data));
export const deleteJob        = (id: string) => safe(() => api.delete(`/jobs/${id}`).then(r => r.data));
export const submitUrls       = (data: unknown) => safe(() => api.post('/jobs/by-urls', data).then(r => r.data));

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
