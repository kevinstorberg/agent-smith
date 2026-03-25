import { Routes, Route, NavLink, Navigate } from 'react-router';
import { HarnessIndexPage } from './pages/HarnessIndexPage';
import { HarnessDetailPage } from './pages/HarnessDetailPage';
import { HarnessCreatePage } from './pages/HarnessCreatePage';
import { MemoryPage } from './pages/MemoryPage';
import { EvalsPage } from './pages/EvalsPage';

const HARNESS_TYPES = [
  { path: 'rules', label: 'Rules', type: 'rule' },
  { path: 'skills', label: 'Skills', type: 'skill' },
  { path: 'tools', label: 'Tools', type: 'tool' },
  { path: 'hooks', label: 'Hooks', type: 'hook' },
];

export default function App() {
  return (
    <div className="app">
      <div className="app-header">
        <h1>Agent Smith</h1>
      </div>
      <nav className="tab-nav">
        {HARNESS_TYPES.map(t => (
          <NavLink key={t.path} to={`/harness/${t.path}`}
            className={({isActive}) => isActive ? 'active' : ''}>
            {t.label}
          </NavLink>
        ))}
        <NavLink to="/memory" className={({isActive}) => isActive ? 'active' : ''}>Memory</NavLink>
        <NavLink to="/evals" className={({isActive}) => isActive ? 'active' : ''}>Evals</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<Navigate to="/harness/rules" replace />} />
        <Route path="/harness/rules" element={<HarnessIndexPage type="rule" />} />
        <Route path="/harness/skills" element={<HarnessIndexPage type="skill" />} />
        <Route path="/harness/tools" element={<HarnessIndexPage type="tool" />} />
        <Route path="/harness/hooks" element={<HarnessIndexPage type="hook" />} />
        <Route path="/harness/rule/new" element={<HarnessCreatePage />} />
        <Route path="/harness/skill/new" element={<HarnessCreatePage />} />
        <Route path="/harness/tool/new" element={<HarnessCreatePage />} />
        <Route path="/harness/hook/new" element={<HarnessCreatePage />} />
        <Route path="/harness/:type/:id" element={<HarnessDetailPage />} />
        <Route path="/memory" element={<MemoryPage />} />
        <Route path="/evals" element={<EvalsPage />} />
      </Routes>
    </div>
  );
}
