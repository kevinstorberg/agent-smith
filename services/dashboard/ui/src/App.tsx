import { useState } from 'react';
import { TabNav } from './components/TabNav';
import { HarnessPage } from './pages/HarnessPage';
import { MemoryPage } from './pages/MemoryPage';
import { EvalsPage } from './pages/EvalsPage';

const TABS = ['Harness', 'Memory', 'Evals'];

export default function App() {
  const [tab, setTab] = useState('Harness');

  return (
    <div className="app">
      <div className="app-header">
        <h1>Agent Smith</h1>
      </div>
      <TabNav tabs={TABS} active={tab} onChange={setTab} />
      {tab === 'Harness' && <HarnessPage />}
      {tab === 'Memory' && <MemoryPage />}
      {tab === 'Evals' && <EvalsPage />}
    </div>
  );
}
