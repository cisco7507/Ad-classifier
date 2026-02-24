import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { getClusterJobs, submitUrls } from '../lib/api';
import type { JobStatus } from '../lib/api';
import { PlayIcon, UpdateIcon, MagnifyingGlassIcon, ClockIcon } from '@radix-ui/react-icons';
import { formatDistanceToNow } from 'date-fns';

export function Jobs() {
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  
  // Submit Form State
  const [submitLoading, setSubmitLoading] = useState(false);
  const [urls, setUrls] = useState('https://www.youtube.com/watch?v=M7FIvfx5J10');
  const [mode, setMode] = useState('pipeline');
  const [categories, setCategories] = useState('Automotive, Technology, Food');
  const [provider, setProvider] = useState('Ollama');
  const [modelName, setModelName] = useState('qwen3-vl:8b-instruct');
  const [ocrEngine, setOcrEngine] = useState('EasyOCR');
  const [scanMode, setScanMode] = useState('Tail Only');
  const [enableVision, setEnableVision] = useState(true);
  
  // Filtering
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const fetchJobs = async () => {
    try {
      const data = await getClusterJobs();
      setJobs(data);
      setLastUpdated(new Date());
    } catch {} finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 2000);
    return () => clearInterval(interval);
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!urls.trim()) return;
    setSubmitLoading(true);
    
    try {
        const urlList = urls.split('\\n').filter(u => u.trim());
        await submitUrls({
            urls: urlList,
            mode,
            settings: {
                categories,
                provider,
                model_name: modelName,
                ocr_engine: ocrEngine,
                ocr_mode: '🚀 Fast',
                scan_mode: scanMode,
                override: false,
                enable_search: false,
                enable_vision: enableVision,
                context_size: 8192,
                workers: 1
            }
        });
        setUrls('');
        fetchJobs();
    } catch (err) {
        console.error(err);
    } finally {
        setSubmitLoading(false);
    }
  };

  const filteredJobs = jobs.filter(j => {
      if (statusFilter !== 'all' && j.status !== statusFilter) return false;
      if (search && !j.job_id.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      {/* Submit Job Form */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
         <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2"><PlayIcon className="w-5 h-5 text-primary-400" /> Start Analysis Job</h2>
         <form onSubmit={handleSubmit} className="flex flex-col gap-4">
             <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
                 <div className="lg:col-span-3">
                     <textarea 
                        value={urls}
                        onChange={e => setUrls(e.target.value)}
                        placeholder="Enter URLs (one per line)..."
                        className="w-full h-32 p-3 text-sm bg-slate-950 border border-slate-800 rounded-lg text-slate-300 focus:ring-1 focus:ring-primary-500 font-mono shadow-inner resize-none"
                     />
                 </div>
                 <div className="flex flex-col justify-end">
                     <button 
                        type="submit" 
                        disabled={submitLoading || !urls.trim()}
                        className="w-full h-12 bg-primary-600 hover:bg-primary-500 active:bg-primary-700 text-white font-bold rounded-lg shadow disabled:opacity-50 transition-colors uppercase tracking-wider text-sm flex items-center justify-center gap-2"
                     >
                         {submitLoading ? <UpdateIcon className="animate-spin w-4 h-4" /> : <PlayIcon className="w-4 h-4" />}
                         {submitLoading ? 'Submitting...' : 'Execute'}
                     </button>
                 </div>
             </div>
             
             {/* Configuration Panel */}
             <div className="grid grid-cols-2 md:grid-cols-4 gap-3 bg-slate-950/50 p-4 rounded-lg border border-slate-800/50">
                 <div className="space-y-1">
                     <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Mode</label>
                     <select value={mode} onChange={e => setMode(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300">
                         <option value="pipeline">Standard Pipeline</option>
                         <option value="agent">ReACT Agent (Slow)</option>
                     </select>
                 </div>
                 <div className="space-y-1">
                     <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">LLM Provider</label>
                     <input value={provider} onChange={e => setProvider(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300" />
                 </div>
                 <div className="space-y-1">
                     <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Model Configuration</label>
                     <input value={modelName} onChange={e => setModelName(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300" />
                 </div>
                 <div className="space-y-1">
                     <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">OCR Engine</label>
                     <select value={ocrEngine} onChange={e => setOcrEngine(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300">
                         <option value="EasyOCR">EasyOCR</option>
                         <option value="Florence-2 (Microsoft)">Florence-2</option>
                         <option value="Disabled">Disabled</option>
                     </select>
                 </div>
                 <div className="space-y-1">
                     <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Scan Strategy</label>
                     <select value={scanMode} onChange={e => setScanMode(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300">
                         <option value="Tail Only">Tail Only</option>
                         <option value="Full Video">Full Video</option>
                     </select>
                 </div>
                 <div className="space-y-1">
                     <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Vision Analysis</label>
                     <select value={enableVision ? 'true' : 'false'} onChange={e => setEnableVision(e.target.value === 'true')} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300">
                         <option value="true">Enabled (SigLIP)</option>
                         <option value="false">Disabled</option>
                     </select>
                 </div>
                 <div className="md:col-span-4 space-y-1">
                     <label className="text-xs uppercase tracking-wider font-semibold text-slate-500">Target Categories (Comma Separated)</label>
                     <input value={categories} onChange={e => setCategories(e.target.value)} className="w-full h-8 text-xs bg-slate-900 border border-slate-800 rounded px-2 text-slate-300 font-mono" />
                 </div>
             </div>
         </form>
      </div>

      {/* Jobs Table Panel */}
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
                      <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search node UUID..." className="pl-8 pr-3 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded text-slate-300 w-48 focus:ring-1 focus:ring-primary-500 font-mono" />
                  </div>
                  <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="py-1.5 px-3 text-xs bg-slate-950 border border-slate-800 rounded text-slate-300 font-medium tracking-wide">
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
                          <th className="px-6 py-4">Job Target</th>
                          <th className="px-6 py-4">Status</th>
                          <th className="px-6 py-4">Stage</th>
                          <th className="px-6 py-4">Stage Detail</th>
                          <th className="px-6 py-4 text-right">Progress</th>
                          <th className="px-6 py-4">Created</th>
                      </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/50">
                      {loading && jobs.length === 0 ? (
                          <tr><td colSpan={6} className="px-6 py-12 text-center text-slate-500">Syncing node cluster state...</td></tr>
                      ) : filteredJobs.length === 0 ? (
                          <tr><td colSpan={6} className="px-6 py-12 text-center text-slate-500">No telemetry found matching filters.</td></tr>
                      ) : filteredJobs.map(job => (
                          <tr key={job.job_id} className="hover:bg-slate-800/20 transition-colors group">
                              <td className="px-6 py-4">
                                  <div className="flex flex-col gap-1">
                                      <Link to={`/jobs/${job.job_id}`} className="font-mono text-xs text-primary-400 group-hover:text-primary-300 transition-colors">{job.job_id}</Link>
                                      <span className="text-[10px] text-slate-500 font-mono max-w-xs truncate">{job.url}</span>
                                  </div>
                              </td>
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
                              <td className="px-6 py-4 text-[10px] uppercase font-bold tracking-widest text-slate-400">
                                  {job.stage || 'unknown'}
                              </td>
                              <td className="px-6 py-4 text-xs text-slate-400 max-w-xs truncate" title={job.stage_detail || ''}>
                                  {job.stage_detail || '—'}
                              </td>
                              <td className="px-6 py-4 font-mono text-xs text-right text-slate-300">
                                  {job.status === 'processing' ? `${job.progress.toFixed(1)}%` : job.status === 'completed' ? '100%' : '---'}
                              </td>
                              <td className="px-6 py-4 font-mono text-[10px] text-slate-500">
                                  {job.created_at}
                              </td>
                          </tr>
                      ))}
                  </tbody>
              </table>
          </div>
      </div>
    </div>
  );
}
