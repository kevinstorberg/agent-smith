import { useState } from 'react';
import { NavLink } from 'react-router';
import { api } from '../api';

const HARNESS_LINKS = [
  { path: '/harness/rules', label: 'Rules' },
  { path: '/harness/skills', label: 'Skills' },
  { path: '/harness/tools', label: 'Tools' },
  { path: '/harness/hooks', label: 'Hooks' },
];

function navClass({ isActive }: { isActive: boolean }): string {
  return `sidebar-link${isActive ? ' active' : ''}`;
}

export function Sidebar() {
  const [syncing, setSyncing] = useState(false);
  const [unsyncing, setUnsyncing] = useState(false);

  async function handleSync() {
    setSyncing(true);
    try {
      const res = await api.harness.sync();
      if (!res.success) {
        alert(`Sync failed:\n${res.stderr || res.stdout}`);
      }
    } catch (err) {
      alert(`Sync error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSyncing(false);
    }
  }

  async function handleUnsync() {
    if (!confirm('Remove all synced agent files?')) return;
    setUnsyncing(true);
    try {
      const res = await api.harness.unsync();
      if (!res.success) {
        alert('Unsync failed');
      }
    } catch (err) {
      alert(`Unsync error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setUnsyncing(false);
    }
  }

  return (
    <nav className="sidebar">
      <div className="sidebar-title">Agent Smith</div>

      <div className="sidebar-section">
        {HARNESS_LINKS.map(link => (
          <NavLink key={link.path} to={link.path} className={navClass}>
            {link.label}
          </NavLink>
        ))}
      </div>

      <div className="sidebar-section">
        <NavLink to="/memory" className={navClass}>Memory</NavLink>
        <NavLink to="/evals" className={navClass}>Evals</NavLink>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-actions">
          <button onClick={handleSync} disabled={syncing} className="sidebar-btn">
            {syncing ? 'Syncing...' : 'Sync'}
          </button>
          <button onClick={handleUnsync} disabled={unsyncing} className="sidebar-btn sidebar-btn-danger">
            {unsyncing ? 'Unsyncing...' : 'Unsync'}
          </button>
        </div>
      </div>
    </nav>
  );
}
