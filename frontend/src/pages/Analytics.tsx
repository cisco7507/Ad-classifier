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
    const p50Values = series.map((row) => row.p50);
    const p90Values = series.map((row) => row.p90);
    const p95Values = series.map((row) => row.p95);
    const p99Values = series.map((row) => row.p99);

    return {
      backgroundColor: 'transparent',
      animationDuration: 600,
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(2, 6, 23, 0.95)',
        borderColor: 'rgba(56, 189, 248, 0.35)',
        textStyle: { color: '#e2e8f0' },
      },
      legend: {
        top: 8,
        textStyle: { color: '#94a3b8' },
      },
      grid: {
        left: 40,
        right: 20,
        top: 48,
        bottom: 28,
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        data: xValues,
        boundaryGap: false,
        axisLabel: { color: '#64748b', fontSize: 10 },
        axisLine: { lineStyle: { color: '#334155' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#94a3b8',
          formatter: (value: number) => `${Math.round(value)}s`,
        },
        splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.16)' } },
        axisLine: { lineStyle: { color: '#334155' } },
      },
      series: [
        {
          name: 'Median (P50)',
          type: 'line',
          data: p50Values,
          smooth: true,
          symbol: 'circle',
          symbolSize: 5,
          lineStyle: { width: 2.8, color: '#22d3ee' },
          itemStyle: { color: '#22d3ee' },
          emphasis: { focus: 'series' },
        },
        {
          name: 'P90',
          type: 'line',
          data: p90Values,
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 1.5, color: '#a78bfa', type: 'dashed' },
          areaStyle: { color: 'rgba(167, 139, 250, 0.12)' },
          emphasis: { focus: 'series' },
        },
        {
          name: 'P95',
          type: 'line',
          data: p95Values,
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 1.8, color: '#f472b6' },
          areaStyle: { color: 'rgba(244, 114, 182, 0.08)' },
          emphasis: { focus: 'series' },
        },
        {
          name: 'P99',
          type: 'line',
          data: p99Values,
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 1.2, color: '#fb7185', type: 'dotted' },
          emphasis: { focus: 'series' },
        },
      ],
    };
  }, [data?.duration_series]);

  if (loading) {
    return (
      <div className="p-8 text-gray-500 flex items-center gap-2 animate-pulse">
        <UpdateIcon className="animate-spin" /> Loading analytics…
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex items-center justify-between">
        <h2 className="text-3xl font-bold tracking-tight text-gray-900 flex items-center gap-2">
          <BarChartIcon className="w-6 h-6 text-primary-600" /> Analytics Dashboard
        </h2>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg flex items-center gap-3">
          <ExclamationTriangleIcon className="w-4 h-4" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">Completed Jobs</div>
          <div className="text-3xl font-bold text-gray-900 font-mono">{totals.completed}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">P50</div>
          <div className="text-3xl font-bold text-cyan-700 font-mono">{formatSeconds(percentiles.p50)}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">P90</div>
          <div className="text-3xl font-bold text-violet-700 font-mono">{formatSeconds(percentiles.p90)}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">P95</div>
          <div className="text-3xl font-bold text-pink-700 font-mono">{formatSeconds(percentiles.p95)}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">P99</div>
          <div className="text-3xl font-bold text-rose-700 font-mono">{formatSeconds(percentiles.p99)}</div>
        </div>
      </div>

      {totals.completed === 0 ? (
        <div className="bg-white border border-gray-200 rounded-xl p-12 text-center text-gray-500 shadow-sm">
          No duration analytics yet. Complete some jobs to populate percentile trends.
        </div>
      ) : (
        <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4 shadow-2xl">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
                Job Duration Percentiles
              </h3>
              <p className="text-xs text-slate-500">
                Median and upper-tail bounds across recent completion windows.
              </p>
            </div>
            <div className="rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-[11px] text-slate-300">
              Samples: {percentiles.count}
            </div>
          </div>
          <ReactECharts option={durationOption} style={{ height: 420, width: '100%' }} notMerge lazyUpdate />
        </div>
      )}
    </div>
  );
}
