import { useState } from 'react';
import { NavLink } from 'react-router';
import { api } from '../api';
import { useNotification } from '../context/useNotification';

const HARNESS_LINKS = [
  { path: '/harness/agents', label: 'Agents' },
  { path: '/harness/hooks', label: 'Hooks' },
  { path: '/harness/rules', label: 'Rules' },
  { path: '/harness/skills', label: 'Skills' },
  { path: '/harness/tools', label: 'Tools' },
];

function navClass({ isActive }: { isActive: boolean }): string {
  return `sidebar-link${isActive ? ' active' : ''}`;
}

export function Sidebar() {
  const [syncing, setSyncing] = useState(false);
  const [unsyncing, setUnsyncing] = useState(false);
  const { notify } = useNotification();

  async function handleSync() {
    setSyncing(true);
    try {
      const res = await api.harness.sync();
      if (res.success) {
        notify('Sync complete', 'success');
      } else {
        notify(`Sync failed: ${res.stderr || res.stdout}`, 'error');
      }
    } catch (err) {
      notify(`Sync error: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setSyncing(false);
    }
  }

  async function handleUnsync() {
    if (!confirm('Remove all synced agent files?')) return;
    setUnsyncing(true);
    try {
      const res = await api.harness.unsync();
      if (res.success) {
        const count = res.removed?.length || 0;
        notify(`Unsynced — ${count} item${count !== 1 ? 's' : ''} removed`, 'success');
      } else {
        notify('Unsync failed', 'error');
      }
    } catch (err) {
      notify(`Unsync error: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setUnsyncing(false);
    }
  }

  return (
    <nav className="sidebar">
      <div className="sidebar-header">
        <img src="/agent_smith_logo.svg" alt="Agent Smith" className="sidebar-logo" />
        <div className="sidebar-title">Agent Smith</div>
      </div>

      <div className="sidebar-section">
        {HARNESS_LINKS.map(link => (
          <NavLink key={link.path} to={link.path} className={navClass}>
            {link.label}
          </NavLink>
        ))}
      </div>

      <div className="sidebar-section">
        <NavLink to="/memory" className={navClass}>Memory</NavLink>
        <NavLink to="/plans" className={navClass}>Plans</NavLink>
      </div>

      <div className="sidebar-section">
        <NavLink to="/eval-configs" className={navClass}>Evals</NavLink>
        <NavLink to="/evals" className={navClass}>Results</NavLink>
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
