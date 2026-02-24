import { useEffect, useState, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getJob, getJobResult, getJobEvents, getJobArtifacts } from '../lib/api';
import type { JobStatus } from '../lib/api';
import { ArrowLeftIcon, FileTextIcon, MagicWandIcon, DownloadIcon, CheckCircledIcon, ExclamationTriangleIcon } from '@radix-ui/react-icons';

export function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<JobStatus | null>(null);
  const [result, setResult] = useState<any>(null);
  const [events, setEvents] = useState<string[]>([]);
  const [artifacts, setArtifacts] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let unmounted = false;
    if (!id) return;

    const poll = async () => {
      try {
        const j = await getJob(id);
        if (unmounted) return;
        setJob(j);

        if (j.status === 'completed' || j.status === 'failed') {
          try {
            const r = await getJobResult(id);
            if (r.result && !unmounted) setResult(r.result);
          } catch {}
          try {
            const a = await getJobArtifacts(id);
            if (a.artifacts && !unmounted) setArtifacts(a.artifacts);
          } catch {}
        }
        
        if (j.mode === 'agent' && (j.status === 'processing' || j.status === 'completed')) {
            try {
              const e = await getJobEvents(id);
              if (e.events && !unmounted) setEvents(e.events);
            } catch {}
        }
        
        if (!unmounted && j.status !== 'completed' && j.status !== 'failed') {
          setTimeout(poll, 1500);
        }
      } catch (err) {
        if (!unmounted && !job) setLoading(false);
      } finally {
        if (!unmounted) setLoading(false);
      }
    };
    poll();

    return () => { unmounted = true; };
  }, [id]);

  useEffect(() => {
    if (containerRef.current) {
        containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [events]);

  if (loading && !job) {
    return <div className="p-8 text-slate-400 flex items-center gap-2 animate-pulse">Loading job...</div>;
  }

  if (!job) {
    return (
      <div className="p-8 text-red-500 bg-red-500/10 border border-red-500/20 rounded-lg max-w-xl mx-auto flex flex-col items-center py-12">
        <ExclamationTriangleIcon className="w-12 h-12 mb-4" />
        <h2 className="text-xl font-bold mb-2">Job Not Found</h2>
        <p className="text-red-400 mb-6 text-sm">The requested job ID {id} does not exist or has been deleted.</p>
        <Link to="/jobs" className="text-sm text-slate-300 bg-slate-800 hover:bg-slate-700 px-4 py-2 rounded transition-colors flex items-center gap-2">
            <ArrowLeftIcon /> Back to Jobs
        </Link>
      </div>
    );
  }

  const progressPercent = Math.round(job.progress);

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-24 animate-in fade-in duration-500">
      <div className="flex items-center gap-4 text-sm text-slate-400 mb-2">
        <Link to="/jobs" className="hover:text-primary-400 flex items-center gap-1 transition-colors">
          <ArrowLeftIcon /> Jobs
        </Link>
        <span>/</span>
        <span className="font-mono text-slate-300">{job.job_id}</span>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-sm flex flex-col gap-6 relative overflow-hidden">
        {/* Header Ribbon */}
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
            
            <div className="text-sm text-slate-400 break-all max-w-3xl font-mono opacity-80 bg-slate-950/50 p-2 rounded border border-slate-800">
                {job.url}
            </div>
          </div>
          
          <div className="flex flex-col items-end gap-1 text-sm text-slate-500">
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

      {result && Array.isArray(result) && result.length > 0 && result[0]?.Brand !== 'Err' && (
        <div className="grid gap-6 animate-in slide-in-from-bottom-4 duration-500 fill-mode-forwards">
          <h2 className="text-xl font-bold text-white flex items-center gap-2"><CheckCircledIcon className="text-emerald-400" /> Final Classification</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
             <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl shadow-sm hover:shadow-md transition-shadow">
                <div className="text-xs uppercase text-slate-500 font-bold tracking-wider mb-2">Category</div>
                <div className="text-2xl font-bold bg-gradient-to-r from-emerald-400 to-emerald-200 bg-clip-text text-transparent">{result[0].Category || 'None'}</div>
             </div>
             <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl shadow-sm hover:shadow-md transition-shadow">
                <div className="text-xs uppercase text-slate-500 font-bold tracking-wider mb-2">Brand Detected</div>
                <div className="text-2xl font-bold text-white drop-shadow-sm">{result[0].Brand || 'N/A'}</div>
             </div>
             <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl shadow-sm hover:shadow-md transition-shadow">
                <div className="text-xs uppercase text-slate-500 font-bold tracking-wider mb-2">Confidence Score</div>
                <div className="text-2xl font-bold text-cyan-400 drop-shadow-sm">{result[0].Confidence}</div>
             </div>
          </div>
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl shadow-sm text-sm text-slate-300 leading-relaxed font-serif tracking-wide">
             <div className="text-xs uppercase text-slate-500 font-bold tracking-wider mb-3 font-sans">Reasoning</div>
             {result[0].Reasoning}
          </div>
        </div>
      )}

      {job.mode === 'agent' && events.length > 0 && (
         <div className="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden shadow-inner flex flex-col animate-in slide-in-from-bottom-4 duration-500 delay-100 fill-mode-forwards">
            <div className="bg-slate-900/80 px-4 py-3 border-b border-slate-800 font-semibold text-slate-300 flex items-center gap-2">
                <MagicWandIcon className="text-fuchsia-400" /> Agent Sub-Routine Log
            </div>
            <div className="p-4 h-96 overflow-y-auto space-y-2 font-mono text-xs text-slate-400" ref={containerRef}>
                {events.map((evt, i) => (
                    <div key={i} className="border-b border-slate-800/50 pb-2 mb-2 last:border-0 whitespace-pre-wrap">{evt}</div>
                ))}
            </div>
         </div>
      )}
      
      {artifacts && artifacts.frames && artifacts.frames.length > 0 && (
         <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm animate-in slide-in-from-bottom-4 duration-500 delay-200 fill-mode-forwards">
            <div className="bg-slate-900/80 px-6 py-4 border-b border-slate-800 font-semibold text-slate-300">
                Extracted Frames Gallery ({artifacts.frames.length})
            </div>
            <div className="p-6 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                {artifacts.frames.map((frame: any, idx: number) => (
                    <div key={idx} className="aspect-video bg-slate-950 rounded border border-slate-800 overflow-hidden relative group">
                        <img 
                            src={frame.data} 
                            alt={`Frame ${frame.timestamp_ms}ms`}
                            className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-500"
                        />
                        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 to-transparent p-2 text-[10px] font-mono text-emerald-400">
                            {frame.timestamp_ms}ms
                        </div>
                    </div>
                ))}
            </div>
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
