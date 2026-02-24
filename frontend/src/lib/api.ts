import axios from 'axios';

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL,
});

export interface ClusterNode {
  nodes: Record<string, string>;
  status: Record<string, boolean>;
  self: string;
}

export interface JobSettings {
  categories: string;
  provider: string;
  model_name: string;
  ocr_engine: string;
  ocr_mode: string;
  scan_mode: string;
  override: boolean;
  enable_search: boolean;
  enable_vision: boolean;
  context_size: number;
  workers: number;
}

export interface JobStatus {
  job_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  progress: number;
  error?: string;
  settings?: JobSettings;
  mode: string;
  url: string;
}

export const getClusterNodes = async () => (await api.get<ClusterNode>('/cluster/nodes')).data;
export const getClusterJobs = async () => (await api.get<JobStatus[]>('/cluster/jobs')).data;
export const getJob = async (id: string) => (await api.get<JobStatus>(`/jobs/${id}`)).data;
export const getJobResult = async (id: string) => (await api.get(`/jobs/${id}/result`)).data;
export const getJobArtifacts = async (id: string) => (await api.get(`/jobs/${id}/artifacts`)).data;
export const getJobEvents = async (id: string) => (await api.get(`/jobs/${id}/events`)).data;
export const deleteJob = async (id: string) => (await api.delete(`/jobs/${id}`)).data;
export const submitUrls = async (data: any) => (await api.post('/jobs/by-urls', data)).data;
