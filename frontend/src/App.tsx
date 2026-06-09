import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router';
import { Sidebar } from './components/Sidebar';
import { NotificationBar } from './components/NotificationBar';
import { NotificationProvider } from './context/NotificationContext';

const HarnessIndexPage = lazy(() =>
  import('./pages/HarnessIndexPage').then((module) => ({ default: module.HarnessIndexPage })),
);
const HarnessDetailPage = lazy(() =>
  import('./pages/HarnessDetailPage').then((module) => ({ default: module.HarnessDetailPage })),
);
const HarnessCreatePage = lazy(() =>
  import('./pages/HarnessCreatePage').then((module) => ({ default: module.HarnessCreatePage })),
);
const MemoryPage = lazy(() => import('./pages/MemoryPage').then((module) => ({ default: module.MemoryPage })));
const EvalsPage = lazy(() => import('./pages/EvalsPage').then((module) => ({ default: module.EvalsPage })));
const EvalDetailPage = lazy(() =>
  import('./pages/EvalDetailPage').then((module) => ({ default: module.EvalDetailPage })),
);
const PlansIndexPage = lazy(() =>
  import('./pages/PlansIndexPage').then((module) => ({ default: module.PlansIndexPage })),
);
const PlanDetailPage = lazy(() =>
  import('./pages/PlanDetailPage').then((module) => ({ default: module.PlanDetailPage })),
);
const JobsIndexPage = lazy(() => import('./pages/JobsIndexPage').then((module) => ({ default: module.JobsIndexPage })));
const JobDetailPage = lazy(() => import('./pages/JobDetailPage').then((module) => ({ default: module.JobDetailPage })));
const EvalSuitesPage = lazy(() =>
  import('./pages/EvalSuitesPage').then((module) => ({ default: module.EvalSuitesPage })),
);
const EvalSuiteDetailPage = lazy(() =>
  import('./pages/EvalSuiteDetailPage').then((module) => ({ default: module.EvalSuiteDetailPage })),
);

export default function App() {
  return (
    <NotificationProvider>
      <div className="app">
        <Sidebar />
        <div className="main-content">
          <NotificationBar />
          <Suspense fallback={<div className="page-loading">Loading...</div>}>
            <Routes>
              <Route path="/" element={<Navigate to="/harness/rules" replace />} />
              <Route path="/harness/rules" element={<HarnessIndexPage type="rule" />} />
              <Route path="/harness/skills" element={<HarnessIndexPage type="skill" />} />
              <Route path="/harness/tools" element={<HarnessIndexPage type="tool" />} />
              <Route path="/harness/hooks" element={<HarnessIndexPage type="hook" />} />
              <Route path="/harness/agents" element={<HarnessIndexPage type="agent" />} />
              <Route path="/harness/rule/new" element={<HarnessCreatePage />} />
              <Route path="/harness/skill/new" element={<HarnessCreatePage />} />
              <Route path="/harness/tool/new" element={<HarnessCreatePage />} />
              <Route path="/harness/hook/new" element={<HarnessCreatePage />} />
              <Route path="/harness/agent/new" element={<HarnessCreatePage />} />
              <Route path="/harness/:type/:id" element={<HarnessDetailPage />} />
              <Route path="/memory" element={<MemoryPage />} />
              <Route path="/evals" element={<EvalsPage />} />
              <Route path="/evals/:id" element={<EvalDetailPage />} />
              <Route path="/plans" element={<PlansIndexPage />} />
              <Route path="/plans/new" element={<PlanDetailPage />} />
              <Route path="/plans/:id" element={<PlanDetailPage />} />
              <Route path="/jobs" element={<JobsIndexPage />} />
              <Route path="/jobs/new" element={<JobDetailPage />} />
              <Route path="/jobs/:id" element={<JobDetailPage />} />
              <Route path="/eval-configs" element={<EvalSuitesPage />} />
              <Route path="/eval-configs/new" element={<EvalSuiteDetailPage />} />
              <Route path="/eval-configs/:id" element={<EvalSuiteDetailPage />} />
            </Routes>
          </Suspense>
        </div>
      </div>
    </NotificationProvider>
  );
}
