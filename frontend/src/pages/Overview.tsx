import { useEffect, useState } from 'react';
import { getClusterNodes, getClusterJobs } from '../lib/api';
import type { ClusterNode, JobStatus } from '../lib/api';
import { Share1Icon, ExclamationTriangleIcon } from '@radix-ui/react-icons';

export function Overview() {
  const [nodes, setNodes] = useState<ClusterNode | null>(null);
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let unmounted = false;
    
    const poll = async () => {
      try {
        const [n, j] = await Promise.all([getClusterNodes(), getClusterJobs()]);
        if (unmounted) return;
        setNodes(n);
        setJobs(j);
        setError('');
      } catch (err: any) {
        if (!unmounted) setError('Failed to fetch cluster data');
      }
      if (!unmounted) setTimeout(poll, 3000);
    };
    poll();
    
    return () => { unmounted = true; };
  }, []);

  const processing = jobs.filter(j => j.status === 'processing').length;
  const queued = jobs.filter(j => j.status === 'queued').length;
  const completed = jobs.filter(j => j.status === 'completed').length;
  const failed = jobs.filter(j => j.status === 'failed').length;

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex items-center justify-between">
        <h2 className="text-3xl font-bold tracking-tight text-white flex items-center gap-2">
          <Share1Icon className="w-6 h-6 text-primary-400" />
          Execution Cluster
        </h2>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-400 p-4 rounded-lg flex items-center gap-3 shadow-lg">
          <ExclamationTriangleIcon />
          <span>{error}</span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {[
          { label: 'Processing', value: processing, color: 'text-blue-400', bg: 'bg-blue-500/10' },
          { label: 'Queued', value: queued, color: 'text-amber-400', bg: 'bg-amber-500/10' },
          { label: 'Completed', value: completed, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
          { label: 'Failed', value: failed, color: 'text-red-400', bg: 'bg-red-500/10' },
        ].map(kpi => (
          <div key={kpi.label} className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm flex flex-col items-center justify-center transform transition-transform hover:scale-[1.02]">
            <span className="text-sm font-medium text-slate-400 mb-1">{kpi.label}</span>
            <span className={`text-4xl font-bold ${kpi.color} drop-shadow-md`}>{kpi.value}</span>
          </div>
        ))}
      </div>

      <div className="bg-slate-900 rounded-xl border border-slate-800 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/50">
          <h3 className="font-semibold text-slate-200">Worker Nodes</h3>
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
              {nodes && Object.entries(nodes.nodes).map(([name, url]) => {
                const isUp = nodes.status[name];
                const isSelf = name === nodes.self;
                return (
                  <tr key={name} className="hover:bg-slate-800/20 transition-colors">
                    <td className="px-6 py-4 font-medium text-slate-200 flex items-center gap-2">
                       {name} {isSelf && <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary-500/20 text-primary-300 font-mono">SELF</span>}
                    </td>
                    <td className="px-6 py-4 text-slate-400 font-mono text-xs">{url}</td>
                    <td className="px-6 py-4">
                      <div className="flex justify-end">
                        {isUp ? (
                          <div className="flex items-center gap-1.5 text-emerald-400 bg-emerald-400/10 px-2 py-1 rounded-md text-xs font-medium border border-emerald-400/20">
                            <span className="relative flex h-2 w-2">
                              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                            </span>
                            ONLINE
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5 text-red-400 bg-red-400/10 px-2 py-1 rounded-md text-xs font-medium border border-red-400/20">
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500"></span>
                            OFFLINE
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!nodes && (
            <div className="py-12 flex justify-center text-slate-500">Loading nodes...</div>
          )}
        </div>
      </div>
    </div>
  );
}
