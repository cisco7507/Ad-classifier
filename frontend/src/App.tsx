import { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Overview } from './pages/Overview';
import { Jobs } from './pages/Jobs';
import { JobDetail } from './pages/JobDetail';

const Analytics = lazy(async () => ({ default: (await import('./pages/Analytics')).Analytics }));
const Benchmark = lazy(async () => ({ default: (await import('./pages/Benchmark')).Benchmark }));

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<div className="p-8 text-gray-500">Loading…</div>}>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="benchmark" element={<Benchmark />} />
            <Route path="jobs" element={<Jobs />} />
            <Route path="jobs/:id" element={<JobDetail />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
