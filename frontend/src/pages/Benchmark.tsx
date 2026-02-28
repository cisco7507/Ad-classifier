import { useEffect, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import {
  ExclamationTriangleIcon,
  RocketIcon,
  UpdateIcon,
} from '@radix-ui/react-icons';
import {
  createBenchmarkTruth,
  getBenchmarkSuiteResults,
  getBenchmarkSuites,
  getBenchmarkTruths,
  getSystemProfile,
  runBenchmarkSuite,
} from '../lib/api';
import type {
  BenchmarkPoint,
  BenchmarkSuiteResults,
  BenchmarkSuiteSummary,
  BenchmarkTruth,
  SystemProfile,
} from '../lib/api';

function formatSeconds(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value < 60) return `${value.toFixed(1)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
}

function formatGbFromMb(valueMb: number | null | undefined): string {
  if (valueMb == null || !Number.isFinite(valueMb)) return '—';
  return `${(valueMb / 1024).toFixed(1)} GB`;
}

function safePercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value.toFixed(1)}%`;
}

export function Benchmark() {
  const [profile, setProfile] = useState<SystemProfile | null>(null);
  const [truths, setTruths] = useState<BenchmarkTruth[]>([]);
  const [suites, setSuites] = useState<BenchmarkSuiteSummary[]>([]);
  const [selectedSuiteId, setSelectedSuiteId] = useState('');
  const [suiteResults, setSuiteResults] = useState<BenchmarkSuiteResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');

  const [truthName, setTruthName] = useState('Golden Video');
  const [truthVideoUrl, setTruthVideoUrl] = useState('');
  const [truthExpectedOcr, setTruthExpectedOcr] = useState('');
  const [truthCategories, setTruthCategories] = useState('');
  const [runTruthId, setRunTruthId] = useState('');
  const [runCategories, setRunCategories] = useState('');

  const fetchBaseData = async () => {
    const [profilePayload, truthPayload, suitePayload] = await Promise.all([
      getSystemProfile(),
      getBenchmarkTruths(),
      getBenchmarkSuites(),
    ]);
    setProfile(profilePayload);
    setTruths(truthPayload.truths || []);
    setSuites(suitePayload.suites || []);
    if (!selectedSuiteId && suitePayload.suites?.length) {
      setSelectedSuiteId(suitePayload.suites[0].suite_id);
    }
    if (!runTruthId && truthPayload.truths?.length) {
      setRunTruthId(truthPayload.truths[0].truth_id);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        await fetchBaseData();
        if (!cancelled) setError('');
      } catch (err: any) {
        if (!cancelled) setError(err?.message || 'Failed to load benchmark data');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void tick();
    const interval = setInterval(() => {
      void tick();
    }, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (!selectedSuiteId) {
      setSuiteResults(null);
      return;
    }
    let cancelled = false;
    const refreshResults = async () => {
      try {
        const results = await getBenchmarkSuiteResults(selectedSuiteId);
        if (cancelled) return;
        setSuiteResults(results);
        const runningSuite = results.status === 'running';
        if (!runningSuite) return;
      } catch (err: any) {
        if (cancelled) return;
        setError(err?.message || 'Failed to load benchmark results');
      }
    };
    void refreshResults();
    const interval = setInterval(() => {
      void refreshResults();
    }, 4000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [selectedSuiteId]);

  const scatterOption: EChartsOption = useMemo(() => {
    const points: BenchmarkPoint[] = suiteResults?.points || [];
    return {
      backgroundColor: 'transparent',
      animationDuration: 600,
      grid: { left: 48, right: 24, top: 30, bottom: 42, containLabel: true },
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(2,6,23,0.95)',
        borderColor: 'rgba(56,189,248,0.4)',
        textStyle: { color: '#e2e8f0' },
        formatter: (params: any) => {
          const point = params?.data?.meta as BenchmarkPoint | undefined;
          if (!point) return 'No data';
          return [
            `<strong>${point.label}</strong>`,
            `Duration: ${formatSeconds(point.x_duration_seconds)}`,
            `Composite Accuracy: ${safePercent(point.y_composite_accuracy_pct)}`,
            `Classification: ${safePercent((point.classification_accuracy || 0) * 100)}`,
            `OCR: ${safePercent((point.ocr_accuracy || 0) * 100)}`,
          ].join('<br/>');
        },
      },
      xAxis: {
        name: 'Duration (seconds)',
        nameLocation: 'middle',
        nameGap: 28,
        type: 'value',
        axisLabel: { color: '#94a3b8' },
        axisLine: { lineStyle: { color: '#334155' } },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.16)' } },
      },
      yAxis: {
        name: 'Composite Accuracy %',
        nameLocation: 'middle',
        nameGap: 42,
        type: 'value',
        min: 0,
        max: 100,
        axisLabel: { color: '#94a3b8' },
        axisLine: { lineStyle: { color: '#334155' } },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.16)' } },
      },
      series: [
        {
          type: 'scatter',
          symbolSize: 10,
          itemStyle: {
            color: '#22d3ee',
            borderColor: '#7dd3fc',
            borderWidth: 1,
            shadowBlur: 8,
            shadowColor: 'rgba(34, 211, 238, 0.45)',
          },
          data: points.map((point) => ({
            value: [point.x_duration_seconds, point.y_composite_accuracy_pct],
            meta: point,
          })),
        },
      ],
    };
  }, [suiteResults]);

  const createTruthDisabled = running || !truthName.trim() || !truthVideoUrl.trim();
  const runDisabled = running || !runTruthId;

  const handleCreateTruth = async () => {
    setRunning(true);
    try {
      await createBenchmarkTruth({
        name: truthName.trim(),
        video_url: truthVideoUrl.trim(),
        expected_ocr_text: truthExpectedOcr,
        expected_categories: truthCategories
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean),
      });
      const truthPayload = await getBenchmarkTruths();
      setTruths(truthPayload.truths || []);
      if (truthPayload.truths?.length && !runTruthId) {
        setRunTruthId(truthPayload.truths[0].truth_id);
      }
      setError('');
    } catch (err: any) {
      setError(err?.message || 'Failed to create benchmark truth');
    } finally {
      setRunning(false);
    }
  };

  const handleRunSuite = async () => {
    setRunning(true);
    try {
      const result = await runBenchmarkSuite({
        truth_id: runTruthId,
        categories: runCategories,
      });
      const suiteId = String(result?.suite_id || '');
      if (suiteId) {
        setSelectedSuiteId(suiteId);
      }
      const suitePayload = await getBenchmarkSuites();
      setSuites(suitePayload.suites || []);
      setError('');
    } catch (err: any) {
      setError(err?.message || 'Failed to start benchmark suite');
    } finally {
      setRunning(false);
    }
  };

  if (loading) {
    return (
      <div className="p-8 text-gray-500 flex items-center gap-2 animate-pulse">
        <UpdateIcon className="animate-spin" /> Loading benchmark tools…
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex items-center gap-2">
        <RocketIcon className="w-6 h-6 text-primary-600" />
        <h2 className="text-3xl font-bold tracking-tight text-gray-900">Benchmarking</h2>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg flex items-center gap-3">
          <ExclamationTriangleIcon className="w-4 h-4" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 text-slate-100">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300">Host Hardware Profile</h3>
          <span className="text-[11px] text-slate-400">Detected at {profile?.timestamp || '—'}</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <div className="rounded border border-slate-800 bg-slate-900 p-2">CPU (logical): {profile?.hardware.cpu_count_logical ?? '—'}</div>
          <div className="rounded border border-slate-800 bg-slate-900 p-2">RAM: {formatGbFromMb(profile?.hardware.total_ram_mb)}</div>
          <div className="rounded border border-slate-800 bg-slate-900 p-2">Accelerator: {profile?.hardware.accelerator || 'cpu'}</div>
          <div className="rounded border border-slate-800 bg-slate-900 p-2">VRAM: {profile?.hardware.total_vram_mb ?? '—'} MB</div>
        </div>
        <div className="text-[11px] text-slate-500 mt-2">VRAM falls back to host RAM estimate when accelerator-specific telemetry is unavailable.</div>
        {(profile?.warnings || []).length > 0 && (
          <div className="mt-3 space-y-2">
            {profile!.warnings.map((warning, idx) => (
              <div key={`${warning.model}-${idx}`} className="rounded border border-amber-700/40 bg-amber-900/20 p-2 text-amber-200 text-xs">
                {warning.message}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3">
          <h3 className="text-sm font-semibold text-gray-800">Create Golden Video Truth</h3>
          <input
            value={truthName}
            onChange={(event) => setTruthName(event.target.value)}
            placeholder="Truth set name"
            className="w-full h-10 px-3 text-sm border border-gray-200 rounded"
          />
          <input
            value={truthVideoUrl}
            onChange={(event) => setTruthVideoUrl(event.target.value)}
            placeholder="Video URL or absolute server path"
            className="w-full h-10 px-3 text-sm border border-gray-200 rounded"
          />
          <textarea
            value={truthCategories}
            onChange={(event) => setTruthCategories(event.target.value)}
            placeholder="Expected categories (comma separated)"
            className="w-full h-20 px-3 py-2 text-sm border border-gray-200 rounded"
          />
          <textarea
            value={truthExpectedOcr}
            onChange={(event) => setTruthExpectedOcr(event.target.value)}
            placeholder="Expected OCR corpus"
            className="w-full h-20 px-3 py-2 text-sm border border-gray-200 rounded"
          />
          <button
            type="button"
            disabled={createTruthDisabled}
            onClick={handleCreateTruth}
            className="h-10 px-4 rounded bg-primary-600 text-white text-sm font-semibold disabled:opacity-50"
          >
            Create Truth
          </button>
        </div>

        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3">
          <h3 className="text-sm font-semibold text-gray-800">Run Benchmark Suite</h3>
          <select
            value={runTruthId}
            onChange={(event) => setRunTruthId(event.target.value)}
            className="w-full h-10 px-3 text-sm border border-gray-200 rounded"
          >
            <option value="">Select Golden Truth</option>
            {truths.map((truth) => (
              <option key={truth.truth_id} value={truth.truth_id}>
                {truth.name}
              </option>
            ))}
          </select>
          <input
            value={runCategories}
            onChange={(event) => setRunCategories(event.target.value)}
            placeholder="Optional categories override"
            className="w-full h-10 px-3 text-sm border border-gray-200 rounded"
          />
          <button
            type="button"
            disabled={runDisabled}
            onClick={handleRunSuite}
            className="h-10 px-4 rounded bg-emerald-600 text-white text-sm font-semibold disabled:opacity-50"
          >
            Launch Cartesian Benchmark
          </button>
          <div className="text-xs text-gray-500">
            Benchmarks enqueue permutations across scan strategy, OCR engine/mode, and provider-model combinations.
          </div>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-800">Benchmark Suites</h3>
          <select
            value={selectedSuiteId}
            onChange={(event) => setSelectedSuiteId(event.target.value)}
            className="h-9 px-2 text-xs border border-gray-200 rounded"
          >
            <option value="">Select suite</option>
            {suites.map((suite) => (
              <option key={suite.suite_id} value={suite.suite_id}>
                {suite.suite_id} · {suite.truth_name || suite.truth_id}
              </option>
            ))}
          </select>
        </div>

        {suiteResults ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div className="rounded border border-gray-200 p-2">Status: {suiteResults.status}</div>
            <div className="rounded border border-gray-200 p-2">Total: {suiteResults.total_jobs}</div>
            <div className="rounded border border-gray-200 p-2">Completed: {suiteResults.completed_jobs}</div>
            <div className="rounded border border-gray-200 p-2">Failed: {suiteResults.failed_jobs}</div>
          </div>
        ) : (
          <div className="text-sm text-gray-500">Select a suite to inspect benchmark scatter results.</div>
        )}
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4 shadow-2xl">
        <div className="mb-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
            Duration vs Composite Accuracy
          </h3>
          <p className="text-xs text-slate-500">
            Each dot is a benchmark permutation. Lower X and higher Y is better (Pareto frontier).
          </p>
        </div>
        <ReactECharts option={scatterOption} style={{ height: 460, width: '100%' }} notMerge lazyUpdate />
      </div>
    </div>
  );
}
