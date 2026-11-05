import { Fragment, type ReactNode } from 'react';
import { Routes, Route, Navigate, useLocation, useParams } from 'react-router';
import { HarnessIndexPage } from './pages/HarnessIndexPage';
import { HarnessDetailPage } from './pages/HarnessDetailPage';
import { HarnessCreatePage } from './pages/HarnessCreatePage';
import { MemoryPage } from './pages/MemoryPage';
import { MeetingsIndexPage } from './pages/MeetingsIndexPage';
import { MeetingDetailPage } from './pages/MeetingDetailPage';
import { ProfileDetailPage } from './pages/ProfileDetailPage';
import { ProfilesIndexPage } from './pages/ProfilesIndexPage';
import { EvalsPage } from './pages/EvalsPage';
import { EvalDetailPage } from './pages/EvalDetailPage';
import { PlansIndexPage } from './pages/PlansIndexPage';
import { PlanDetailPage } from './pages/PlanDetailPage';
import { ActionItemsIndexPage } from './pages/ActionItemsIndexPage';
import { ActionItemDetailPage } from './pages/ActionItemDetailPage';
import { JobsIndexPage } from './pages/JobsIndexPage';
import { JobDetailPage } from './pages/JobDetailPage';
import { ProposalsIndexPage } from './pages/ProposalsIndexPage';
import { ProposalDetailPage } from './pages/ProposalDetailPage';
import { AuditIndexPage } from './pages/AuditIndexPage';
import { AuditDetailPage } from './pages/AuditDetailPage';
import { EvalSuitesPage } from './pages/EvalSuitesPage';
import { EvalSuiteDetailPage } from './pages/EvalSuiteDetailPage';
import { ChatPage } from './pages/ChatPage';
import { CostsPage } from './pages/CostsPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { Sidebar } from './components/Sidebar';
import { NotificationBar } from './components/NotificationBar';
import { NotificationProvider } from './context/NotificationContext';

function LegacyProfileRedirect() {
  const { id } = useParams();
  const { search, hash } = useLocation();
  return (
    <Navigate
      to={`/profiles/${encodeURIComponent(id!)}${search}${hash}`}
      replace
    />
  );
}

function ProfileRoute() {
  const { id } = useParams();
  return <ProfileDetailPage key={id} />;
}

function MeetingRoute() {
  const { id } = useParams();
  return <MeetingDetailPage key={id} />;
}

function DetailRoute({ children }: { children: ReactNode }) {
  const { type, id } = useParams();
  return (
    <Fragment key={JSON.stringify([type, id ?? 'new'])}>{children}</Fragment>
  );
}

export default function App() {
  return (
    <NotificationProvider>
      <div className="app">
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        <Sidebar />
        <main className="main-content" id="main-content" tabIndex={-1}>
          <NotificationBar />
          <Routes>
            <Route path="/" element={<Navigate to="/action-items" replace />} />
            <Route
              path="/harness/rules"
              element={<HarnessIndexPage key="rule" type="rule" />}
            />
            <Route
              path="/harness/skills"
              element={<HarnessIndexPage key="skill" type="skill" />}
            />
            <Route
              path="/harness/tools"
              element={<HarnessIndexPage key="tool" type="tool" />}
            />
            <Route
              path="/harness/hooks"
              element={<HarnessIndexPage key="hook" type="hook" />}
            />
            <Route
              path="/harness/agents"
              element={<HarnessIndexPage key="agent" type="agent" />}
            />
            <Route path="/harness/rule/new" element={<HarnessCreatePage />} />
            <Route path="/harness/skill/new" element={<HarnessCreatePage />} />
            <Route path="/harness/tool/new" element={<HarnessCreatePage />} />
            <Route path="/harness/hook/new" element={<HarnessCreatePage />} />
            <Route path="/harness/agent/new" element={<HarnessCreatePage />} />
            <Route
              path="/harness/:type/:id"
              element={
                <DetailRoute>
                  <HarnessDetailPage />
                </DetailRoute>
              }
            />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/action-items" element={<ActionItemsIndexPage />} />
            <Route
              path="/action-items/new"
              element={<ActionItemDetailPage />}
            />
            <Route
              path="/action-items/:id"
              element={<ActionItemDetailPage />}
            />
            <Route path="/meetings" element={<MeetingsIndexPage />} />
            <Route path="/meetings/:id" element={<MeetingRoute />} />
            <Route
              path="/meetings/profiles/:id"
              element={<LegacyProfileRedirect />}
            />
            <Route path="/profiles" element={<ProfilesIndexPage />} />
            <Route path="/profiles/:id" element={<ProfileRoute />} />
            <Route path="/evals" element={<EvalsPage />} />
            <Route
              path="/evals/:id"
              element={
                <DetailRoute>
                  <EvalDetailPage />
                </DetailRoute>
              }
            />
            <Route path="/plans" element={<PlansIndexPage />} />
            <Route
              path="/plans/new"
              element={
                <DetailRoute>
                  <PlanDetailPage />
                </DetailRoute>
              }
            />
            <Route
              path="/plans/:id"
              element={
                <DetailRoute>
                  <PlanDetailPage />
                </DetailRoute>
              }
            />
            <Route path="/proposals" element={<ProposalsIndexPage />} />
            <Route
              path="/proposals/:id"
              element={
                <DetailRoute>
                  <ProposalDetailPage />
                </DetailRoute>
              }
            />
            <Route path="/audit" element={<AuditIndexPage />} />
            <Route
              path="/audit/:id"
              element={
                <DetailRoute>
                  <AuditDetailPage />
                </DetailRoute>
              }
            />
            <Route path="/jobs" element={<JobsIndexPage />} />
            <Route path="/jobs/new" element={<JobDetailPage />} />
            <Route path="/jobs/:id" element={<JobDetailPage />} />
            <Route path="/eval-configs" element={<EvalSuitesPage />} />
            <Route
              path="/eval-configs/new"
              element={
                <DetailRoute>
                  <EvalSuiteDetailPage />
                </DetailRoute>
              }
            />
            <Route
              path="/eval-configs/:id"
              element={
                <DetailRoute>
                  <EvalSuiteDetailPage />
                </DetailRoute>
              }
            />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/costs" element={<CostsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>
      </div>
    </NotificationProvider>
  );
}
