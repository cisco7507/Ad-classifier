import { useEffect, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { BarChartIcon, ExclamationTriangleIcon, UpdateIcon } from '@radix-ui/react-icons';
import { getClusterAnalytics } from '../lib/api';
import type { AnalyticsData } from '../lib/api';

const PALETTE = ['#4f46e5', '#6366f1', '#818cf8', '#22c55e', '#f59e0b', '#ef4444', '#06b6d4', '#14b8a6', '#ec4899', '#8b5cf6'];

function formatSeconds(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value < 60) return `${value.toFixed(1)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
}

function chartCard(title: string, option: EChartsOption) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-gray-800 mb-3">{title}</h3>
      <ReactECharts option={option} style={{ height: 320, width: '100%' }} notMerge lazyUpdate />
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
  const successRate = totals.total > 0 ? (totals.completed / totals.total) * 100 : 0;
  const topBrand = data?.top_brands?.[0]?.brand || '—';

  const topBrandsOption: EChartsOption = useMemo(() => {
    const rows = [...(data?.top_brands || [])].sort((a, b) => b.count - a.count).slice(0, 20);
    const labels = rows.map((r) => r.brand).reverse();
    const values = rows.map((r) => r.count).reverse();
    return {
      animationDuration: 1000,
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 120, right: 24, top: 8, bottom: 16, containLabel: true },
      xAxis: { type: 'value', axisLabel: { color: '#6b7280' }, splitLine: { lineStyle: { color: '#e5e7eb' } } },
      yAxis: { type: 'category', data: labels, axisLabel: { color: '#374151' } },
      series: [
        {
          type: 'bar',
          data: values,
          barWidth: 14,
          label: { show: true, position: 'right', color: '#374151', fontWeight: 600 },
          itemStyle: {
            borderRadius: [0, 8, 8, 0],
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 1,
              y2: 0,
              colorStops: [
                { offset: 0, color: '#818cf8' },
                { offset: 1, color: '#4f46e5' },
              ],
            },
          },
        },
      ],
    };
  }, [data]);

  const categoriesOption: EChartsOption = useMemo(() => {
    const rows = (data?.categories || []).slice(0, 25);
    return {
      tooltip: {
        trigger: 'item',
        formatter: (params: any) => `${params?.name || 'unknown'}<br/>${params?.value || 0} jobs`,
      },
      color: PALETTE,
      series: [
        {
          name: 'Categories',
          type: 'treemap',
          roam: false,
          breadcrumb: { show: false },
          nodeClick: false,
          upperLabel: { show: false },
          leafDepth: 1,
          itemStyle: {
            borderColor: '#fff',
            borderWidth: 1,
            gapWidth: 2,
          },
          label: {
            show: true,
            formatter: (params: any) => {
              const name = String(params?.name || '');
              const value = Number(params?.value || 0);
              return name.length > 26 ? `${name.slice(0, 25)}…\n${value}` : `${name}\n${value}`;
            },
            color: '#1f2937',
            fontSize: 11,
            overflow: 'truncate',
          },
          emphasis: {
            label: {
              show: true,
              color: '#111827',
            },
            itemStyle: {
              borderColor: '#111827',
              borderWidth: 1,
            },
          },
          data: rows.map((row) => ({
            name: row.category,
            value: row.count,
          })),
        },
      ],
    };
  }, [data]);

  const dailyOption: EChartsOption = useMemo(() => {
    const outcomes = data?.daily_outcomes || [];
    const days = Array.from(new Set(outcomes.map((d) => d.day))).sort();
    const completedMap = new Map<string, number>();
    const failedMap = new Map<string, number>();
    for (const row of outcomes) {
      const status = (row.status || '').toLowerCase();
      if (status === 'completed') completedMap.set(row.day, row.count);
      if (status === 'failed') failedMap.set(row.day, row.count);
    }
    const completed = days.map((day) => completedMap.get(day) || 0);
    const failed = days.map((day) => failedMap.get(day) || 0);

    return {
      tooltip: { trigger: 'axis' },
      legend: { top: 0, textStyle: { color: '#4b5563' } },
      grid: { left: 24, right: 24, top: 40, bottom: 24, containLabel: true },
      xAxis: { type: 'category', data: days, boundaryGap: false, axisLabel: { color: '#6b7280' } },
      yAxis: { type: 'value', axisLabel: { color: '#6b7280' }, splitLine: { lineStyle: { color: '#e5e7eb' } } },
      series: [
        {
          name: 'Completed',
          type: 'line',
          smooth: true,
          stack: 'total',
          symbol: 'none',
          lineStyle: { color: '#10b981', width: 2 },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(16, 185, 129, 0.35)' },
                { offset: 1, color: 'rgba(16, 185, 129, 0.03)' },
              ],
            },
          },
          data: completed,
        },
        {
          name: 'Failed',
          type: 'line',
          smooth: true,
          stack: 'total',
          symbol: 'none',
          lineStyle: { color: '#ef4444', width: 2 },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(239, 68, 68, 0.30)' },
                { offset: 1, color: 'rgba(239, 68, 68, 0.03)' },
              ],
            },
          },
          data: failed,
        },
      ],
    };
  }, [data]);

  const gaugeOptions = useMemo(() => {
    const modes = data?.avg_duration_by_mode || [];
    const fallback = ['pipeline', 'agent'];
    const selected = fallback.map((name) => {
      const row = modes.find((mode) => (mode.mode || '').toLowerCase() === name);
      return {
        label: name === 'pipeline' ? 'Pipeline' : 'Agent',
        avg: row?.avg_duration ?? 0,
        count: row?.count ?? 0,
      };
    });

    return selected.map((item) => {
      const maxValue = Math.max(120, Math.ceil((item.avg || 1) * 1.6));
      return {
        title: `${item.label} Avg Duration`,
        option: {
          series: [
            {
              type: 'gauge',
              min: 0,
              max: maxValue,
              splitNumber: 6,
              axisLine: {
                lineStyle: {
                  width: 14,
                  color: [
                    [Math.min(30 / maxValue, 1), '#10b981'],
                    [Math.min(60 / maxValue, 1), '#f59e0b'],
                    [1, '#ef4444'],
                  ],
                },
              },
              pointer: { width: 4, length: '70%' },
              axisTick: { show: false },
              splitLine: { length: 10, lineStyle: { color: '#9ca3af' } },
              axisLabel: { color: '#6b7280' },
              detail: {
                valueAnimation: true,
                formatter: (value: number) => `${value.toFixed(1)}s`,
                color: '#111827',
                fontSize: 18,
                offsetCenter: [0, '62%'],
              },
              title: { color: '#4b5563', offsetCenter: [0, '90%'] },
              data: [{ value: item.avg || 0, name: `${item.count} jobs` }],
            },
          ],
        } as EChartsOption,
      };
    });
  }, [data]);

  const radarOption: EChartsOption = useMemo(() => {
    const scans = data?.avg_duration_by_scan || [];
    const indicators = scans.map((row) => ({
      name: row.scan_mode || 'unknown',
      max: Math.max(10, Math.ceil((row.avg_duration || 0) * 1.5) || 10),
    }));
    const values = scans.map((row) => row.avg_duration || 0);
    return {
      tooltip: {},
      radar: {
        indicator: indicators,
        splitArea: { areaStyle: { color: ['rgba(99, 102, 241, 0.04)', 'rgba(99, 102, 241, 0.01)'] } },
        axisName: { color: '#4b5563' },
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: values,
              name: 'Avg duration',
              areaStyle: { color: 'rgba(79, 70, 229, 0.25)' },
              lineStyle: { color: '#4f46e5' },
              itemStyle: { color: '#4f46e5' },
            },
          ],
        },
      ],
    };
  }, [data]);

  const treemapOption: EChartsOption = useMemo(() => {
    const providers = data?.providers || [];
    return {
      tooltip: { formatter: '{b}: {c}' },
      series: [
        {
          type: 'treemap',
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          label: { show: true, formatter: '{b}\n{c}', color: '#111827', fontWeight: 600 },
          itemStyle: { borderColor: '#fff', borderWidth: 2, gapWidth: 2 },
          levels: [{ color: PALETTE }],
          data: providers.map((row) => ({ name: row.provider || 'unknown', value: row.count })),
        },
      ],
    };
  }, [data]);

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

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">Total Jobs Processed</div>
          <div className="text-3xl font-bold text-gray-900 font-mono">{totals.total}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">Success Rate</div>
          <div className="text-3xl font-bold text-emerald-700 font-mono">{totals.total ? `${successRate.toFixed(1)}%` : '—'}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">Average Duration</div>
          <div className="text-3xl font-bold text-primary-700 font-mono">{formatSeconds(totals.avg_duration)}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">Most Common Brand</div>
          <div className="text-lg font-bold text-gray-900 truncate">{topBrand}</div>
        </div>
      </div>

      {totals.total === 0 ? (
        <div className="bg-white border border-gray-200 rounded-xl p-12 text-center text-gray-500 shadow-sm">
          No analytics data yet. Complete some jobs to see trends.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {chartCard('Top Brands', topBrandsOption)}
            {chartCard('Category Distribution', categoriesOption)}
          </div>

          {chartCard('Success / Failure Over Time', dailyOption)}

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {gaugeOptions.map((gauge) => (
              <div key={gauge.title} className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
                <h3 className="text-sm font-semibold text-gray-800 mb-3">{gauge.title}</h3>
                <ReactECharts option={gauge.option} style={{ height: 280, width: '100%' }} notMerge lazyUpdate />
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {chartCard('Processing Time by Scan Strategy', radarOption)}
            {chartCard('Provider Usage', treemapOption)}
          </div>
        </>
      )}
    </div>
  );
}
