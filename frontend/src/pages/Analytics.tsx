import { useEffect, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { BarChartIcon, ExclamationTriangleIcon, UpdateIcon } from '@radix-ui/react-icons';
import { getClusterAnalytics } from '../lib/api';
import type { AnalyticsData, DurationSeriesPoint } from '../lib/api';

function formatSeconds(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value < 60) return `${value.toFixed(1)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
}

function formatBucketLabel(bucket: string): string {
  if (!bucket) return '—';
  const normalized = bucket.replace('T', ' ');
  if (normalized.length >= 16) return normalized.slice(5, 16);
  return normalized;
}

function sortedDurationSeries(series: DurationSeriesPoint[]): DurationSeriesPoint[] {
  return [...series]
    .sort((a, b) => String(a.bucket || '').localeCompare(String(b.bucket || '')))
    .slice(-48);
}

function MetricPill({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div className="bell-panel p-5">
      <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">{label}</div>
      <div className={`mt-3 text-4xl font-bold ${accent}`}>{value}</div>
    </div>
  );
}

function PathMetricList({
  title,
  subtitle,
  items,
  denominator,
  accent,
}: {
  title: string;
  subtitle: string;
  items: Array<{ attempt_type: string; title: string; count: number }>;
  denominator: number;
  accent: string;
}) {
  return (
    <div className="rounded-[26px] border border-slate-200/70 bg-white/90 p-5 shadow-[0_18px_45px_rgba(15,23,42,0.06)] backdrop-blur">
      <div>
        <h3 className="text-sm font-black uppercase tracking-[0.22em] text-slate-500">{title}</h3>
        <p className="mt-2 text-sm leading-6 text-slate-500">{subtitle}</p>
      </div>
      {items.length === 0 ? (
        <div className="mt-4 rounded-[20px] border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-400">
          No traced jobs yet.
        </div>
      ) : (
        <div className="mt-5 space-y-3">
          {items.map((item) => {
            const pct = denominator > 0 ? Math.max(4, (item.count / denominator) * 100) : 0;
            return (
              <div key={`${title}-${item.attempt_type}`} className="rounded-[18px] border border-slate-200/80 bg-slate-50/70 p-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">{item.title}</div>
                    <div className="mt-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {item.attempt_type}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xl font-black tracking-[-0.04em] text-slate-950">{item.count}</div>
                    <div className="text-xs text-slate-400">
                      {denominator > 0 ? `${Math.round((item.count / denominator) * 100)}% of traced jobs` : '—'}
                    </div>
                  </div>
                </div>
                <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-slate-200/80">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${pct}%`, background: accent }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function Analytics() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const payload = await getClusterAnalytics();
        if (cancelled) return;
        setData(payload);
        setError('');
      } catch (err: any) {
        if (cancelled) return;
        setError(err?.message || 'Failed to load analytics');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    poll();
    const interval = setInterval(poll, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const totals = data?.totals ?? { total: 0, completed: 0, failed: 0, avg_duration: null };
  const pathMetrics = data?.path_metrics ?? { jobs_with_trace: 0, accepted_paths: [], transit_paths: [] };
  const percentiles = data?.duration_percentiles ?? {
    count: 0,
    p50: null,
    p90: null,
    p95: null,
    p99: null,
  };

  const durationOption: EChartsOption = useMemo(() => {
    const series = sortedDurationSeries(data?.duration_series || []);
    const xValues = series.map((row) => formatBucketLabel(row.bucket));

    return {
      backgroundColor: 'transparent',
      animationDuration: 650,
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(0, 31, 68, 0.96)',
        borderColor: 'rgba(191, 220, 242, 0.35)',
        textStyle: { color: '#e2e8f0' },
      },
      legend: {
        top: 8,
        textStyle: { color: '#5e6772' },
      },
      grid: {
        left: 40,
        right: 24,
        top: 54,
        bottom: 30,
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        data: xValues,
        boundaryGap: false,
        axisLabel: { color: '#64748b', fontSize: 10 },
        axisLine: { lineStyle: { color: 'rgba(148,163,184,0.22)' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#94a3b8',
          formatter: (value: number) => `${Math.round(value)}s`,
        },
        splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.12)' } },
        axisLine: { lineStyle: { color: 'rgba(148,163,184,0.22)' } },
      },
      series: [
        {
          name: 'Median (P50)',
          type: 'line',
          data: series.map((row) => row.p50),
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          lineStyle: { width: 3, color: '#0070ce' },
          itemStyle: { color: '#0070ce' },
          emphasis: { focus: 'series' },
        },
        {
          name: 'P90',
          type: 'line',
          data: series.map((row) => row.p90),
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 1.7, color: '#00549a', type: 'dashed' },
          areaStyle: { color: 'rgba(0, 84, 154, 0.08)' },
          emphasis: { focus: 'series' },
        },
        {
          name: 'P95',
          type: 'line',
          data: series.map((row) => row.p95),
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 1.9, color: '#4e9fd4' },
          areaStyle: { color: 'rgba(78, 159, 212, 0.07)' },
          emphasis: { focus: 'series' },
        },
        {
          name: 'P99',
          type: 'line',
          data: series.map((row) => row.p99),
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 1.4, color: '#8aa9c5', type: 'dotted' },
          emphasis: { focus: 'series' },
        },
      ],
    };
  }, [data?.duration_series]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-[24px] border border-slate-200/80 bg-white/80 p-8 text-slate-500 shadow-sm">
        <UpdateIcon className="animate-spin" /> Loading analytics…
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <section className="bell-hero">
        <div className="relative z-10 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <div className="bell-badge">
              <BarChartIcon className="h-3.5 w-3.5" />
              Throughput intelligence
            </div>
            <h2 className="mt-4 max-w-2xl text-[3rem] font-bold text-primary-700">Watch the tails, not just the averages</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
              This dashboard is tuned for operational reliability. Median speed tells you how healthy the system feels. P95 and P99 tell you when rescues, retries, and edge cases are starting to dominate
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-[1.7rem] border border-white/90 bg-white/88 px-4 py-4 shadow-[0_14px_28px_rgba(0,55,120,0.08)]">
              <div className="text-[11px] uppercase tracking-[0.22em] text-slate-400">Completed jobs</div>
              <div className="mt-2 text-4xl font-bold text-slate-950">{totals.completed}</div>
              <div className="mt-2 text-sm text-slate-500">Persistent output volume across the cluster</div>
            </div>
            <div className="rounded-[1.7rem] border border-primary-700/30 bg-primary-700 px-4 py-4 text-white shadow-[0_18px_36px_rgba(0,55,120,0.22)]">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/65">Sample windows</div>
              <div className="mt-2 text-4xl font-bold text-white">{percentiles.count}</div>
              <div className="mt-2 text-sm text-white/72">Recent completion buckets feeding the chart</div>
            </div>
          </div>
        </div>
      </section>

      {error ? (
        <div className="rounded-[24px] border border-rose-200 bg-rose-50 p-4 text-rose-700 shadow-sm">
          <div className="flex items-center gap-3 text-sm">
            <ExclamationTriangleIcon className="h-4 w-4" />
            {error}
          </div>
        </div>
      ) : null}

      <section className="grid grid-cols-2 gap-4 xl:grid-cols-5">
        <MetricPill label="Completed Jobs" value={String(totals.completed)} accent="text-slate-950" />
        <MetricPill label="P50" value={formatSeconds(percentiles.p50)} accent="text-primary-700" />
        <MetricPill label="P90" value={formatSeconds(percentiles.p90)} accent="text-primary-800" />
        <MetricPill label="P95" value={formatSeconds(percentiles.p95)} accent="text-[#4e9fd4]" />
        <MetricPill label="P99" value={formatSeconds(percentiles.p99)} accent="text-slate-700" />
      </section>

      <section className="bell-panel p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-black uppercase tracking-[0.22em] text-slate-500">Path telemetry</h3>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
              Derived from saved processing traces only. This does not add any work to live job execution and helps show which paths are actually carrying the workload.
            </p>
          </div>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            {pathMetrics.jobs_with_trace} traced job{pathMetrics.jobs_with_trace === 1 ? '' : 's'}
          </span>
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <PathMetricList
            title="Accepted paths"
            subtitle="Where jobs finished after the fallback ladder settled on a final answer."
            items={pathMetrics.accepted_paths || []}
            denominator={pathMetrics.jobs_with_trace}
            accent="linear-gradient(135deg, #00549a, #0070ce)"
          />
          <PathMetricList
            title="Transit counts"
            subtitle="How many jobs traversed each stage, including retries that were later rejected."
            items={pathMetrics.transit_paths || []}
            denominator={pathMetrics.jobs_with_trace}
            accent="linear-gradient(135deg, #4e9fd4, #8dbfe3)"
          />
        </div>
      </section>

      {totals.completed === 0 ? (
        <div className="bell-panel p-12 text-center text-slate-500">
          No duration analytics yet. Complete some jobs to populate percentile trends.
        </div>
      ) : (
        <section className="bell-panel p-5">
          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h3 className="text-lg font-bold text-slate-950">Job duration percentiles</h3>
              <p className="mt-1 text-sm text-slate-500">
                Median tracks the common case. The upper bands reveal when the rescue ladder, OCR retries, or provider latency start to stretch the tail.
              </p>
            </div>
            <div className="bell-data-pill">
              Samples: {percentiles.count}
            </div>
          </div>
          <ReactECharts option={durationOption} style={{ height: 440, width: '100%' }} notMerge lazyUpdate />
        </section>
      )}
    </div>
  );
}
