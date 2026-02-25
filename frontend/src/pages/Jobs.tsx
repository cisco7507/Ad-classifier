import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { getClusterJobs, submitFilePath, submitFolderPath, submitUrls } from '../lib/api';
import type { JobStatus, JobSettings } from '../lib/api';
import { PlayIcon, UpdateIcon, MagnifyingGlassIcon, ClockIcon } from '@radix-ui/react-icons';
import { formatDistanceToNow } from 'date-fns';

type InputMode = 'urls' | 'filepath' | 'dirpath';

export function Jobs() {
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  // Submit form state
  const [submitLoading, setSubmitLoading] = useState(false);
  const [inputMode, setInputMode] = useState<InputMode>('urls');
  const [urls, setUrls] = useState('https://www.youtube.com/watch?v=M7FIvfx5J10');
  const [filePath, setFilePath] = useState('');
  const [folderPath, setFolderPath] = useState('');

  const [mode, setMode] = useState('pipeline');
  const [categories, setCategories] = useState('');
  const [provider, setProvider] = useState('Ollama');
  const [modelName, setModelName] = useState('qwen3-vl:8b-instruct');
  const [ocrEngine, setOcrEngine] = useState('EasyOCR');
  const [ocrMode, setOcrMode] = useState('🚀 Fast');
  const [scanMode, setScanMode] = useState('Tail Only');
  const [enableVision, setEnableVision] = useState(true);
  const [enableWebSearch, setEnableWebSearch] = useState(true);
  const [contextSize, setContextSize] = useState(8192);

  // Filtering
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const fetchJobs = async () => {
    try {
      const data = await getClusterJobs();
      setJobs(data);
      setLastUpdated(new Date());
    } catch {
      // no-op
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 4000);
    return () => clearInterval(interval);
  }, []);

  const settingsPayload: JobSettings = useMemo(
    () => ({
      categories,
      provider,
      model_name: modelName,
      ocr_engine: ocrEngine,
      ocr_mode: ocrMode,
      scan_mode: scanMode,
      override: false,
      enable_search: enableWebSearch,
      enable_web_search: enableWebSearch,
      enable_vision: enableVision,
      context_size: contextSize,
    }),
    [
      categories,
      provider,
      modelName,
      ocrEngine,
      ocrMode,
      scanMode,
      enableWebSearch,
      enableVision,
      contextSize,
    ]
  );

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitLoading(true);

    try {
      if (inputMode === 'urls') {
        const urlList = urls
          .split('\n')
          .map((u) => u.trim())
          .filter(Boolean);
        if (!urlList.length) return;
        await submitUrls({ urls: urlList, mode, settings: settingsPayload });
      } else if (inputMode === 'filepath') {
        if (!filePath.trim()) return;
        await submitFilePath({ file_path: filePath, mode, settings: settingsPayload });
      } else {
        if (!folderPath.trim()) return;
        await submitFolderPath({ folder_path: folderPath, mode, settings: settingsPayload });
      }
      await fetchJobs();
    } catch (err) {
      console.error(err);
    } finally {
      setSubmitLoading(false);
    }
  };

  const filteredJobs = jobs.filter((j) => {
    if (statusFilter !== 'all' && j.status !== statusFilter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      j.job_id.toLowerCase().includes(q) ||
      (j.brand || '').toLowerCase().includes(q) ||
      (j.category || '').toLowerCase().includes(q) ||
      (j.url || '').toLowerCase().includes(q)
    );
  });

  const disableSubmit =
    submitLoading ||
    (inputMode === 'urls' && !urls.trim()) ||
    (inputMode === 'filepath' && !filePath.trim()) ||
    (inputMode === 'dirpath' && !folderPath.trim());

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
        <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
          <PlayIcon className="w-5 h-5 text-primary-400" /> Start Analysis Job
        </h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => setInputMode('urls')} className={`px-3 py-1.5 text-xs rounded border ${inputMode === 'urls' ? 'bg-primary-600 border-primary-500 text-white' : 'bg-slate-950 border-slate-800 text-slate-300'}`}>URLs</button>
            <button type="button" onClick={() => setInputMode('filepath')} className={`px-3 py-1.5 text-xs rounded border ${inputMode === 'filepath' ? 'bg-primary-600 border-primary-500 text-white' : 'bg-slate-950 border-slate-800 text-slate-300'}`}>File Path</button>
            <button type="button" onClick={() => setInputMode('dirpath')} className={`px-3 py-1.5 text-xs rounded border ${inputMode === 'dirpath' ? 'bg-primary-600 border-primary-500 text-white' : 'bg-slate-950 border-slate-800 text-slate-300'}`}>Directory Path</button>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
            <div className="lg:col-span-3">
              {inputMode === 'urls' && (
                <textarea
                  value={urls}
                  onChange={(e) => setUrls(e.target.value)}
                  placeholder="Enter URLs (one per line)..."
                  className="w-full h-32 p-3 text-sm bg-slate-950 border border-slate-800 rounded-lg text-slate-300 focus:ring-1 focus:ring-primary-500 font-mono shadow-inner resize-none"
                />
              )}
              {inputMode === 'filepath' && (
                <input
                  value={filePath}
                  onChange={(e) => setFilePath(e.target.value)}
                  placeholder={'C:\\videos\\ad.mp4 or \\\\server\\share\\ads\\spot.mp4'}
                  className="w-full h-12 px-3 text-sm bg-slate-950 border border-slate-800 rounded-lg text-slate-300 focus:ring-1 focus:ring-primary-500 font-mono shadow-inner"
                />
              )}
              {inputMode === 'dirpath' && (
                <input
                  value={folderPath}
                  onChange={(e) => setFolderPath(e.target.value)}
                  placeholder={'C:\\videos\\ads or \\\\server\\share\\ads or /mnt/media/ads'}
                  className="w-full h-12 px-3 text-sm bg-slate-950 border border-slate-800 rounded-lg text-slate-300 focus:ring-1 focus:ring-primary-500 font-mono shadow-inner"
                />
              )}
            </div>
            <div className="flex flex-col justify-end">
              <button
                type="submit"
                disabled={disableSubmit}
                className="w-full h-12 bg-primary-600 hover:bg-primary-500 active:bg-primary-700 text-white font-bold rounded-lg shadow disabled:opacity-50 transition-colors uppercase tracking-wider text-sm flex items-center justify-center gap-2"
              >
                {submitLoading ? <UpdateIcon className="animate-spin w-4 h-4" /> : <PlayIcon className="w-4 h-4" />}
                {submitLoading ? 'Submitting...' : 'Execute'}
              </button>
            </div>
          </div>

          <div className="text-xs text-amber-300 bg-amber-950/30 border border-amber-700/40 rounded px-3 py-2">
            File/Directory paths must be accessible to the backend server (not your browser). UNC paths require server access/permissions.
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 bg-slate-950/50 p-4 rounded-lg border border-slate-800/50">
            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Mode</label>
              <select value={mode} onChange={(e) => setMode(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300">
                <option value="pipeline">Standard Pipeline</option>
                <option value="agent">ReACT Agent</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Web Search</label>
              <select value={enableWebSearch ? 'true' : 'false'} onChange={(e) => setEnableWebSearch(e.target.value === 'true')} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300">
                <option value="true">Enabled</option>
                <option value="false">Disabled</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Scan Strategy</label>
              <select value={scanMode} onChange={(e) => setScanMode(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300">
                <option value="Tail Only">Tail Only</option>
                <option value="Full Video">Full Video</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Vision</label>
              <select value={enableVision ? 'true' : 'false'} onChange={(e) => setEnableVision(e.target.value === 'true')} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300">
                <option value="true">Enabled</option>
                <option value="false">Disabled</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">OCR Engine</label>
              <select value={ocrEngine} onChange={(e) => setOcrEngine(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300">
                <option value="EasyOCR">EasyOCR</option>
                <option value="Florence-2 (Microsoft)">Florence-2</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">OCR Mode</label>
              <select value={ocrMode} onChange={(e) => setOcrMode(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300">
                <option value="🚀 Fast">Fast</option>
                <option value="Detailed">Detailed</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Context Limit</label>
              <input type="number" min={512} step={512} value={contextSize} onChange={(e) => setContextSize(Number(e.target.value || 8192))} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300 font-mono" />
            </div>
            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Provider</label>
              <input value={provider} onChange={(e) => setProvider(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300" />
            </div>
            <div className="space-y-1 md:col-span-2">
              <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Model</label>
              <input value={modelName} onChange={(e) => setModelName(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300" />
            </div>
            <div className="space-y-1 md:col-span-4">
              <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Target Categories (Comma Separated)</label>
              <input value={categories} onChange={(e) => setCategories(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300 font-mono" />
            </div>
          </div>
        </form>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm flex flex-col">
        <div className="px-6 py-4 border-b border-slate-800 bg-slate-900 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <h3 className="font-bold text-white tracking-wide">Job Queue</h3>
            <div className="flex items-center gap-1.5 text-xs text-slate-500 bg-slate-950 px-2 py-1 rounded shadow-inner border border-slate-800">
              <ClockIcon className="w-3 h-3 text-emerald-500" /> Auto-syncing ({formatDistanceToNow(lastUpdated, { addSuffix: true })})
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <MagnifyingGlassIcon className="absolute left-2.5 top-2.5 w-4 h-4 text-slate-500" />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search job, brand, category..." className="pl-8 pr-3 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded text-slate-300 w-56 focus:ring-1 focus:ring-primary-500 font-mono" />
            </div>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="py-1.5 px-3 text-xs bg-slate-950 border border-slate-800 rounded text-slate-300 font-medium tracking-wide">
              <option value="all">ALL STATUSES</option>
              <option value="queued">QUEUED</option>
              <option value="processing">PROCESSING</option>
              <option value="completed">COMPLETED</option>
              <option value="failed">FAILED</option>
            </select>
            <button onClick={fetchJobs} className="p-1.5 bg-slate-800 hover:bg-slate-700 rounded text-slate-300 transition-colors border border-slate-700">
              <UpdateIcon className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="overflow-x-auto min-h-[400px]">
          <table className="w-full text-sm text-left whitespace-nowrap">
            <thead className="text-[10px] uppercase font-bold tracking-wider text-slate-500 bg-slate-950/50">
              <tr>
                <th className="px-6 py-4">Job</th>
                <th className="px-6 py-4">Brand</th>
                <th className="px-6 py-4">Category</th>
                <th className="px-6 py-4">Status</th>
                <th className="px-6 py-4">Mode</th>
                <th className="px-6 py-4">Stage</th>
                <th className="px-6 py-4 text-right">Progress</th>
                <th className="px-6 py-4">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {loading && jobs.length === 0 ? (
                <tr><td colSpan={8} className="px-6 py-12 text-center text-slate-500">Syncing node cluster state...</td></tr>
              ) : filteredJobs.length === 0 ? (
                <tr><td colSpan={8} className="px-6 py-12 text-center text-slate-500">No jobs found.</td></tr>
              ) : filteredJobs.map((job) => (
                <tr key={job.job_id} className="hover:bg-slate-800/20 transition-colors group">
                  <td className="px-6 py-4">
                    <div className="flex flex-col gap-1">
                      <Link to={`/jobs/${job.job_id}`} className="font-mono text-xs text-primary-400 group-hover:text-primary-300 transition-colors">{job.job_id}</Link>
                      <span className="text-[10px] text-slate-500 font-mono max-w-xs truncate">{job.url}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-xs text-slate-300">{job.brand || '—'}</td>
                  <td className="px-6 py-4 text-xs text-slate-300">{job.category || '—'}</td>
                  <td className="px-6 py-4">
                    <span className={`px-2 py-1 rounded inline-flex text-[10px] font-bold tracking-wider uppercase border shadow-inner ${
                      job.status === 'completed' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                      job.status === 'failed' ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                      job.status === 'processing' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                      'bg-amber-500/10 text-amber-500 border-amber-500/20'
                    }`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-[10px] uppercase font-bold tracking-widest text-slate-400">{job.mode || '—'}</td>
                  <td className="px-6 py-4 text-[10px] uppercase font-bold tracking-widest text-slate-400">{job.stage || '—'}</td>
                  <td className="px-6 py-4 font-mono text-xs text-right text-slate-300">
                    {job.status === 'processing' ? `${job.progress.toFixed(1)}%` : job.status === 'completed' ? '100%' : '—'}
                  </td>
                  <td className="px-6 py-4 font-mono text-[10px] text-slate-500">{job.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
