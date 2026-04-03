import { Routes, Route, Navigate } from 'react-router';
import { HarnessIndexPage } from './pages/HarnessIndexPage';
import { HarnessDetailPage } from './pages/HarnessDetailPage';
import { HarnessCreatePage } from './pages/HarnessCreatePage';
import { MemoryPage } from './pages/MemoryPage';
import { EvalsPage } from './pages/EvalsPage';
import { EvalDetailPage } from './pages/EvalDetailPage';
import { PlansIndexPage } from './pages/PlansIndexPage';
import { PlanDetailPage } from './pages/PlanDetailPage';
import { EvalSuitesPage } from './pages/EvalSuitesPage';
import { EvalSuiteDetailPage } from './pages/EvalSuiteDetailPage';
import { Sidebar } from './components/Sidebar';
import { NotificationBar } from './components/NotificationBar';
import { NotificationProvider } from './context/NotificationContext';

export default function App() {
  return (
    <NotificationProvider>
      <div className="app">
        <Sidebar />
        <div className="main-content">
          <NotificationBar />
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
          <Route path="/eval-configs" element={<EvalSuitesPage />} />
          <Route path="/eval-configs/new" element={<EvalSuiteDetailPage />} />
          <Route path="/eval-configs/:id" element={<EvalSuiteDetailPage />} />
          </Routes>
        </div>
      </div>
    </NotificationProvider>
  );
}
