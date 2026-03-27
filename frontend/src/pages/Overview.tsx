import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { API_BASE_URL, getClusterNodes, getClusterJobs, getJobArtifacts, getJobVideoPosterUrl, getJobVideoUrl, setClusterNodeMaintenance } from '../lib/api';
import type { ArtifactFrame, ClusterNode, JobArtifacts, JobStatus } from '../lib/api';
import { ExclamationTriangleIcon, UpdateIcon, LightningBoltIcon, PlayIcon } from '@radix-ui/react-icons';

function NodeBadge({
  name,
  url,
  isUp,
  isSelf,
  isMaintenance,
  isAccepting,
  controlsAvailable,
  busy,
  onToggleMaintenance,
}: {
  name: string;
  url: string;
  isUp: boolean;
  isSelf: boolean;
  isMaintenance: boolean;
  isAccepting: boolean;
  controlsAvailable: boolean;
  busy: boolean;
  onToggleMaintenance: () => void;
}) {
  return (
    <tr className="transition-colors hover:bg-primary-50/50">
      <td className="px-6 py-4 font-semibold text-slate-800">
        <div className="flex items-center gap-2">
          <span>{name}</span>
          {isSelf ? (
            <span className="rounded-full border border-primary-200 bg-primary-50 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary-700">
              Self
            </span>
          ) : null}
        </div>
      </td>
      <td className="px-6 py-4 text-xs font-mono text-slate-500">{url}</td>
      <td className="px-6 py-4">
        <div className="flex flex-wrap items-center justify-end gap-2">
        {isUp ? (
          <span className="inline-flex items-center gap-2 rounded-full border border-primary-200 bg-primary-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-primary-700">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary-300 opacity-70" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary-500" />
            </span>
            Online
          </span>
        ) : (
          <span className="inline-flex items-center gap-2 rounded-full border border-rose-200 bg-rose-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-rose-700">
            <ExclamationTriangleIcon className="h-3.5 w-3.5" />
            Unreachable
          </span>
        )}
        {isUp ? (
          isAccepting ? (
            <span className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-emerald-700">
              Accepting
            </span>
          ) : isMaintenance ? (
            <span className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-amber-700">
              Maintenance
            </span>
          ) : (
            <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-600">
              Admission paused
            </span>
          )
        ) : null}
        {!isUp || !controlsAvailable ? null : (
          <button
            type="button"
            onClick={onToggleMaintenance}
            disabled={busy}
            className={`inline-flex items-center rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] transition-colors ${
              isMaintenance
                ? 'border-primary-200 bg-white text-primary-700 hover:border-primary-300 hover:bg-primary-50'
                : 'border-amber-200 bg-white text-amber-700 hover:border-amber-300 hover:bg-amber-50'
            } disabled:cursor-not-allowed disabled:opacity-50`}
          >
            {busy ? 'Updating…' : isMaintenance ? 'Return to production' : 'Enter maintenance'}
          </button>
        )}
        </div>
      </td>
    </tr>
  );
}

function parseTimestamp(value?: string): number {
  if (!value) return 0;
  const normalized = value.includes('T') ? value : value.replace(' ', 'T');
  const withZone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized) ? normalized : `${normalized}Z`;
  const time = new Date(withZone).getTime();
  return Number.isFinite(time) ? time : 0;
}

function formatRelativeTimestamp(value?: string): string {
  const time = parseTimestamp(value);
  if (!time) return 'Recently updated';
  const diffMs = Date.now() - time;
  const absMs = Math.abs(diffMs);
  const future = diffMs < 0;
  const minutes = Math.round(absMs / 60000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return future ? `In ${minutes}m` : `${minutes}m ago`;
  const hours = Math.round(absMs / 3600000);
  if (hours < 24) return future ? `In ${hours}h` : `${hours}h ago`;
  const days = Math.round(absMs / 86400000);
  if (days < 7) return future ? `In ${days}d` : `${days}d ago`;
  return new Date(time).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatConfidenceLabel(confidence?: number | null): string {
  const numeric = Number(confidence);
  if (!Number.isFinite(numeric)) return 'Confidence pending';
  const normalized = numeric > 1 ? numeric : numeric * 100;
  return `${normalized.toFixed(normalized >= 99.5 ? 0 : 1)}% confident`;
}

function getBrandLabel(job: JobStatus): string {
  const brand = String(job.brand || '').trim();
  if (brand) return brand;
  const category = String(job.category_name || job.category || '').trim();
  if (category) return category;
  return 'Processed ad';
}

function getCategoryLabel(job: JobStatus): string {
  return String(job.category_name || job.category || job.parent_category || job.industry_name || 'Classification ready').trim();
}

function fillJobs(jobs: JobStatus[], count: number): JobStatus[] {
  if (jobs.length === 0 || count <= 0) return [];
  const filled: JobStatus[] = [];
  while (filled.length < count) {
    filled.push(jobs[filled.length % jobs.length]);
  }
  return filled;
}

function resolveMediaUrl(value?: string | null): string | null {
  const raw = String(value || '').trim();
  if (!raw) return null;
  try {
    return new URL(raw, API_BASE_URL).toString();
  } catch {
    return null;
  }
}

function uniqueUrls(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const value of values) {
    const normalized = String(value || '').trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    output.push(normalized);
  }
  return output;
}

function collectFrameUrls(frames?: ArtifactFrame[]): string[] {
  if (!Array.isArray(frames)) return [];
  return frames
    .map((frame) => resolveMediaUrl(frame?.url))
    .filter((value): value is string => Boolean(value));
}

function buildGalleryUrls(job: JobStatus, artifacts?: JobArtifacts | null): string[] {
  const latestFrames = collectFrameUrls(artifacts?.latest_frames);
  const llmFrames = collectFrameUrls(artifacts?.llm_frames);
  const boardImage = resolveMediaUrl(artifacts?.vision_board?.image_url ?? null);
  const poster = getJobVideoPosterUrl(job.job_id);

  return uniqueUrls([...latestFrames, ...llmFrames, boardImage, poster]);
}

type JobVisualMap = Record<string, string[]>;

function ScreeningCard({
  job,
  imageUrl,
  variant,
}: {
  job: JobStatus;
  imageUrl: string;
  variant?: 'compact' | 'strip';
}) {
  const compact = variant === 'compact';
  const strip = variant === 'strip';

  return (
    <Link
      to={`/jobs/${job.job_id}`}
      className={`landing-poster-card group ${compact ? 'landing-poster-card-compact' : ''} ${strip ? 'landing-poster-card-strip' : ''}`.trim()}
    >
      <img
        src={imageUrl}
        alt={`${getBrandLabel(job)} poster`}
        className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-[1.05]"
        loading="lazy"
      />
      <div className="landing-poster-overlay" />
      <div className="landing-poster-meta">
        <div className="landing-poster-eyebrow">{getCategoryLabel(job)}</div>
        <div className="landing-poster-title">{getBrandLabel(job)}</div>
      </div>
    </Link>
  );
}

export function Overview() {
  const [nodes, setNodes] = useState<ClusterNode | null>(null);
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [error, setError] = useState('');
  const [nodeErr, setNodeErr] = useState('');
  const [maintenanceBusy, setMaintenanceBusy] = useState<Record<string, boolean>>({});
  const [featuredIndex, setFeaturedIndex] = useState(0);
  const [jobVisuals, setJobVisuals] = useState<JobVisualMap>({});

  useEffect(() => {
    let unmounted = false;

    const poll = async () => {
      try {
        const j = await getClusterJobs();
        if (!unmounted) {
          setJobs(j);
          setError('');
        }
      } catch (err: any) {
        if (!unmounted) setError(err.message || 'Failed to fetch jobs');
      }

      try {
        const n = await getClusterNodes();
        if (!unmounted) {
          setNodes(n);
          setNodeErr('');
        }
      } catch (err: any) {
        if (!unmounted) setNodeErr(err.message || 'Cannot reach API');
      }

      try {
        if (!unmounted) setTimeout(poll, 3000);
      } catch {
        if (!unmounted) setTimeout(poll, 3000);
      }
    };

    poll();
    return () => {
      unmounted = true;
    };
  }, []);

  const completedJobs = useMemo(
    () =>
      [...jobs]
        .filter((job) => job.status === 'completed')
        .sort((a, b) => parseTimestamp(b.updated_at || b.created_at) - parseTimestamp(a.updated_at || a.created_at)),
    [jobs],
  );

  const featuredJobs = useMemo(() => completedJobs.slice(0, 8), [completedJobs]);
  const leftColumnJobs = useMemo(
    () => fillJobs(featuredJobs.slice(0, 2), Math.min(2, featuredJobs.length)),
    [featuredJobs],
  );
  const rightColumnJobs = useMemo(
    () => fillJobs(featuredJobs.slice(2, 4), Math.min(2, Math.max(featuredJobs.length - 2, 0))),
    [featuredJobs],
  );

  useEffect(() => {
    const jobsToHydrate = completedJobs.slice(0, 8);
    if (jobsToHydrate.length === 0) {
      setJobVisuals((current) => (Object.keys(current).length === 0 ? current : {}));
      return;
    }

    let cancelled = false;

    const hydrateVisuals = async () => {
      const results = await Promise.allSettled(
        jobsToHydrate.map(async (job) => {
          try {
            const payload = await getJobArtifacts(job.job_id);
            return [job.job_id, buildGalleryUrls(job, payload.artifacts)] as const;
          } catch {
            return [job.job_id, buildGalleryUrls(job, null)] as const;
          }
        }),
      );

      if (cancelled) return;

      const nextVisuals: JobVisualMap = {};
      for (const result of results) {
        if (result.status !== 'fulfilled') continue;
        const [jobId, urls] = result.value;
        nextVisuals[jobId] = urls;
      }
      setJobVisuals(nextVisuals);
    };

    hydrateVisuals();
    return () => {
      cancelled = true;
    };
  }, [completedJobs]);

  useEffect(() => {
    if (featuredJobs.length === 0) {
      if (featuredIndex !== 0) setFeaturedIndex(0);
      return;
    }

    if (featuredIndex >= featuredJobs.length) {
      setFeaturedIndex(0);
    }
  }, [featuredIndex, featuredJobs.length]);

  useEffect(() => {
    if (featuredJobs.length <= 1) return;
    const timer = window.setInterval(() => {
      setFeaturedIndex((current) => (current + 1) % featuredJobs.length);
    }, 5200);
    return () => window.clearInterval(timer);
  }, [featuredJobs.length]);

  const onlineNodes = nodes ? Object.values(nodes.status).filter(Boolean).length : 0;
  const totalNodes = nodes ? Object.keys(nodes.status).length : 0;
  const maintenanceApiAvailable = Boolean(
    nodes &&
      Object.keys(nodes.maintenance || {}).length > 0 &&
      Object.keys(nodes.accepting_new_jobs || {}).length > 0,
  );
  const maintenanceNodes = nodes && maintenanceApiAvailable ? Object.values(nodes.maintenance || {}).filter(Boolean).length : 0;
  const featuredJob = featuredJobs[featuredIndex] || null;

  const getVisualUrl = (job: JobStatus, index = 0): string => {
    const visuals = jobVisuals[job.job_id];
    if (visuals && visuals.length > 0) return visuals[Math.min(index, visuals.length - 1)];
    return getJobVideoPosterUrl(job.job_id);
  };

  const refreshCluster = async () => {
    const [n, j] = await Promise.all([
      getClusterNodes(),
      getClusterJobs(),
    ]);
    setNodes(n);
    setJobs(j);
  };

  const toggleMaintenance = async (nodeName: string, nextEnabled: boolean) => {
    setMaintenanceBusy((current) => ({ ...current, [nodeName]: true }));
    try {
      await setClusterNodeMaintenance(nodeName, nextEnabled);
      await refreshCluster();
    } catch (err: any) {
      const message = String(err?.message || `Failed to update maintenance mode for ${nodeName}`);
      if (/not found/i.test(message)) {
        setNodeErr('Maintenance controls require restarting the API nodes so the new maintenance endpoints are loaded.');
      } else {
        setNodeErr(message);
      }
    } finally {
      setMaintenanceBusy((current) => ({ ...current, [nodeName]: false }));
    }
  };

  return (
    <div className="flex min-h-full flex-col gap-6 animate-in fade-in duration-500">
      <section className="landing-hero flex-1">
        <div className="landing-cinema-stage h-full">
          {featuredJob ? (
            <>
              <div className="landing-stage-halo" aria-hidden="true" />
              <div className="landing-cinema-grid">
                <div className="landing-cinema-column">
                  {leftColumnJobs.map((job, index) => (
                    <div key={`${job.job_id}-left-${index}`} className={`landing-float landing-float-${(index % 2) + 1}`}>
                      <ScreeningCard job={job} imageUrl={getVisualUrl(job, 0)} variant="compact" />
                    </div>
                  ))}
                </div>

                <Link to={`/jobs/${featuredJob.job_id}`} className="landing-feature group">
                  <div className="landing-feature-topline">
                    <span className="bell-data-pill border-white/18 bg-white/10 text-white/88">
                      <PlayIcon className="h-3.5 w-3.5" />
                      Now screening
                    </span>
                    <span className="landing-feature-time">{formatRelativeTimestamp(featuredJob.updated_at || featuredJob.created_at)}</span>
                  </div>

                  <div className="landing-feature-media">
                    <video
                      key={featuredJob.job_id}
                      src={getJobVideoUrl(featuredJob.job_id)}
                      poster={getJobVideoPosterUrl(featuredJob.job_id)}
                      className="h-full w-full object-cover"
                      autoPlay
                      muted
                      loop
                      playsInline
                      preload="metadata"
                    />
                    <div className="landing-feature-vignette" aria-hidden="true" />
                  </div>

                  <div className="landing-feature-caption">
                    <div>
                      <div className="landing-feature-kicker">{getCategoryLabel(featuredJob)}</div>
                      <div className="landing-feature-title">{getBrandLabel(featuredJob)}</div>
                    </div>
                    <div className="landing-feature-detail">
                      <span>{formatConfidenceLabel(featuredJob.confidence)}</span>
                      <span>{featuredJob.duration_seconds ? `${featuredJob.duration_seconds.toFixed(1)}s runtime` : 'Duration pending'}</span>
                    </div>
                  </div>
                </Link>

                <div className="landing-cinema-column">
                  {rightColumnJobs.map((job, index) => (
                    <div key={`${job.job_id}-right-${index}`} className={`landing-float landing-float-${((index + 1) % 2) + 1}`}>
                      <ScreeningCard job={job} imageUrl={getVisualUrl(job, 1)} variant="compact" />
                    </div>
                  ))}
                </div>
              </div>
            </>
          ) : (
            <div className="landing-empty-state">
              <div className="bell-badge">
                <LightningBoltIcon className="h-3.5 w-3.5" />
                Waiting for the first finished reel
              </div>
              <h3 className="mt-5 text-3xl font-bold text-white">Complete a job and this stage will light up automatically.</h3>
              <p className="mt-3 max-w-xl text-sm leading-6 text-white/72">
                As soon as Scenalyze finishes a job, its poster and video become part of the landing collage. Until then, the operational shell still tracks queue and node health below.
              </p>
            </div>
          )}
        </div>

      </section>

      {nodeErr ? (
        <div className="rounded-[24px] border border-rose-200 bg-rose-50/90 p-4 text-rose-700 shadow-sm">
          <div className="flex items-start gap-3">
            <ExclamationTriangleIcon className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.2em]">API unreachable</p>
              <p className="mt-1 text-sm text-rose-700/90">{nodeErr}</p>
            </div>
          </div>
        </div>
      ) : null}

      {error && !nodeErr ? (
        <div className="rounded-[24px] border border-rose-200 bg-rose-50/90 p-4 text-rose-700 shadow-sm">
          <div className="flex items-center gap-3 text-sm">
            <ExclamationTriangleIcon className="h-4 w-4" />
            {error}
          </div>
        </div>
      ) : null}

      <section className="bell-panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200/80 bg-primary-50/75 px-6 py-4">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Worker fleet</h3>
            <p className="mt-1 text-sm text-slate-500">Cinematic landing or not, each node still runs as a claim-capable executor with deterministic owner routing and optional maintenance drain mode.</p>
          </div>
          <div className="bell-data-pill">
            <LightningBoltIcon className="h-3.5 w-3.5 text-primary-500" />
            {onlineNodes}/{totalNodes || '—'} online{maintenanceApiAvailable ? ` · ${maintenanceNodes} in maintenance` : ''}
          </div>
        </div>
        {!maintenanceApiAvailable ? (
          <div className="border-t border-slate-200/80 bg-amber-50/80 px-6 py-3 text-sm text-amber-800">
            Restart the API nodes to enable maintenance controls on this fleet view.
          </div>
        ) : null}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[880px] text-left text-sm">
            <thead className="bg-slate-50/80 text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">
              <tr>
                <th className="px-6 py-4">Node</th>
                <th className="px-6 py-4">Internal URL</th>
                <th className="px-6 py-4 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {nodes ? (
                Object.entries(nodes.nodes).map(([name, url]) => (
                  (() => {
                    const hasMaintenanceState = Object.prototype.hasOwnProperty.call(nodes.maintenance || {}, name);
                    const hasAcceptingState = Object.prototype.hasOwnProperty.call(nodes.accepting_new_jobs || {}, name);
                    const isMaintenance = hasMaintenanceState ? Boolean(nodes.maintenance?.[name]) : false;
                    const isAccepting = hasAcceptingState ? Boolean(nodes.accepting_new_jobs?.[name]) : Boolean(nodes.status[name]);
                    return (
                  <NodeBadge
                    key={name}
                    name={name}
                    url={url as string}
                    isUp={nodes.status[name]}
                    isSelf={name === nodes.self}
                    isMaintenance={isMaintenance}
                    isAccepting={isAccepting}
                    controlsAvailable={maintenanceApiAvailable}
                    busy={Boolean(maintenanceBusy[name])}
                    onToggleMaintenance={() => toggleMaintenance(name, !isMaintenance)}
                  />
                    );
                  })()
                ))
              ) : (
                <tr>
                  <td colSpan={3} className="px-6 py-12 text-center text-slate-400">
                    {nodeErr ? (
                      <span className="inline-flex items-center gap-2 text-rose-400">
                        <ExclamationTriangleIcon /> {nodeErr}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-2">
                        <UpdateIcon className="animate-spin" /> Loading nodes…
                      </span>
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
