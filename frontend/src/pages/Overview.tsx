import { useEffect, useState } from 'react';
import { getClusterNodes, getClusterJobs, getMetrics } from '../lib/api';
import type { ClusterNode, JobStatus, Metrics } from '../lib/api';
import { Share1Icon, ExclamationTriangleIcon, UpdateIcon } from '@radix-ui/react-icons';

// ── Node status badge ────────────────────────────────────────────────────────
function NodeBadge({ name, url, isUp, isSelf }: { name: string; url: string; isUp: boolean; isSelf: boolean }) {
  return (
    <tr className="hover:bg-slate-800/20 transition-colors">
      <td className="px-6 py-4 font-medium text-slate-200 flex items-center gap-2">
        {name}
        {isSelf && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary-500/20 text-primary-300 font-mono">SELF</span>
        )}
      </td>
      <td className="px-6 py-4 text-slate-400 font-mono text-xs">{url}</td>
      <td className="px-6 py-4">
        <div className="flex justify-end">
          {isUp ? (
            <div className="flex items-center gap-1.5 text-emerald-400 bg-emerald-400/10 px-2 py-1 rounded-md text-xs font-medium border border-emerald-400/20">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
              </span>
              ONLINE
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-red-400 bg-red-400/10 px-2 py-1 rounded-md text-xs font-medium border border-red-400/20">
              <ExclamationTriangleIcon className="w-3 h-3" />
              UNREACHABLE
            </div>
          )}
        </div>
      </td>
    </tr>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export function Overview() {
  const [nodes,   setNodes]   = useState<ClusterNode | null>(null);
  const [jobs,    setJobs]    = useState<JobStatus[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error,   setError]   = useState('');
  const [nodeErr, setNodeErr] = useState('');

  useEffect(() => {
    let unmounted = false;

    const poll = async () => {
      // Cluster jobs (resilient — partial data is ok)
      try {
        const j = await getClusterJobs();
        if (!unmounted) { setJobs(j); setError(''); }
      } catch (err: any) {
        if (!unmounted) setError(err.message || 'Failed to fetch jobs');
      }

      // Node status (separate so a job-fetch error doesn't hide node info)
      try {
        const n = await getClusterNodes();
        if (!unmounted) { setNodes(n); setNodeErr(''); }
      } catch (err: any) {
        if (!unmounted) setNodeErr(err.message || 'Cannot reach API');
      }

      // Metrics (best-effort)
      try {
        const m = await getMetrics();
        if (!unmounted) setMetrics(m);
      } catch {}

      if (!unmounted) setTimeout(poll, 3000);
    };
    poll();
    return () => { unmounted = true; };
  }, []);

  const processing = jobs.filter(j => j.status === 'processing').length;
  const queued     = jobs.filter(j => j.status === 'queued').length;
  const completed  = jobs.filter(j => j.status === 'completed').length;
  const failed     = jobs.filter(j => j.status === 'failed').length;
  const offlineNodes = nodes ? Object.values(nodes.status).filter(v => !v).length : 0;

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex items-center justify-between">
        <h2 className="text-3xl font-bold tracking-tight text-white flex items-center gap-2">
          <Share1Icon className="w-6 h-6 text-primary-400" />
          Execution Cluster
        </h2>
        {metrics && (
          <span className="text-xs text-slate-500 font-mono bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-md">
            Node: <span className="text-slate-300">{metrics.node}</span>
            &nbsp;·&nbsp;
            Uptime: <span className="text-slate-300">{Math.floor(metrics.uptime_seconds / 60)}m</span>
          </span>
        )}
      </div>

      {/* API unreachable banner */}
      {nodeErr && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 p-4 rounded-lg flex items-center gap-3 shadow-lg">
          <ExclamationTriangleIcon className="w-5 h-5 shrink-0" />
          <div>
            <p className="font-semibold">API Unreachable</p>
            <p className="text-sm text-red-300/80 mt-0.5">{nodeErr}</p>
          </div>
        </div>
      )}

      {/* Partial cluster warning */}
      {!nodeErr && offlineNodes > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/30 text-amber-400 p-4 rounded-lg flex items-center gap-3">
          <ExclamationTriangleIcon className="w-5 h-5 shrink-0" />
          <p className="text-sm">
            <span className="font-semibold">{offlineNodes} node{offlineNodes > 1 ? 's' : ''} unreachable.</span>
            {' '}Jobs from offline nodes may not appear in the queue.
          </p>
        </div>
      )}

      {/* Job error banner */}
      {error && !nodeErr && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-400 p-4 rounded-lg flex items-center gap-3">
          <ExclamationTriangleIcon className="w-4 h-4" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Processing', value: processing, color: 'text-blue-400',    bg: 'bg-blue-500/10',    border: 'border-blue-500/20'    },
          { label: 'Queued',     value: queued,     color: 'text-amber-400',   bg: 'bg-amber-500/10',   border: 'border-amber-500/20'   },
          { label: 'Completed',  value: completed,  color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20' },
          { label: 'Failed',     value: failed,     color: 'text-red-400',     bg: 'bg-red-500/10',     border: 'border-red-500/20'     },
        ].map(kpi => (
          <div key={kpi.label} className={`${kpi.bg} border ${kpi.border} rounded-xl p-6 flex flex-col items-center justify-center transform transition-transform hover:scale-[1.02]`}>
            <span className="text-sm font-medium text-slate-400 mb-1">{kpi.label}</span>
            <span className={`text-4xl font-bold ${kpi.color} drop-shadow-md`}>{kpi.value}</span>
          </div>
        ))}
      </div>

      {/* Metrics strip */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Total Completed (DB)',  value: metrics.jobs_completed },
            { label: 'Total Failed (DB)',     value: metrics.jobs_failed },
            { label: 'Submitted This Session', value: metrics.jobs_submitted_this_process },
            { label: 'API Uptime',            value: `${Math.floor(metrics.uptime_seconds / 60)}m ${metrics.uptime_seconds % 60}s` },
          ].map(m => (
            <div key={m.label} className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-3 flex justify-between items-center">
              <span className="text-xs text-slate-500 font-medium">{m.label}</span>
              <span className="text-sm font-bold text-slate-200 font-mono">{m.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Worker nodes table */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/50">
          <h3 className="font-semibold text-slate-200">Worker Nodes</h3>
          {nodes && (
            <span className="text-xs text-slate-500 font-mono">
              {Object.values(nodes.status).filter(Boolean).length}/{Object.keys(nodes.status).length} online
            </span>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs uppercase text-slate-400 bg-slate-950/50">
              <tr>
                <th className="px-6 py-4 font-medium">Node ID</th>
                <th className="px-6 py-4 font-medium">Internal URL</th>
                <th className="px-6 py-4 font-medium text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {nodes ? (
                Object.entries(nodes.nodes).map(([name, url]) => (
                  <NodeBadge
                    key={name}
                    name={name}
                    url={url as string}
                    isUp={nodes.status[name]}
                    isSelf={name === nodes.self}
                  />
                ))
              ) : (
                <tr>
                  <td colSpan={3} className="px-6 py-12 text-center text-slate-500">
                    {nodeErr ? (
                      <span className="flex items-center justify-center gap-2 text-red-400">
                        <ExclamationTriangleIcon /> {nodeErr}
                      </span>
                    ) : (
                      <span className="flex items-center justify-center gap-2">
                        <UpdateIcon className="animate-spin" /> Loading nodes…
                      </span>
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
