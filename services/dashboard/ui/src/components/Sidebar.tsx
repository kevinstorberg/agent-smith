import { useState } from 'react';
import { NavLink } from 'react-router';
import { api } from '../api';

const HARNESS_LINKS = [
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
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  function showToast(message: string, type: 'success' | 'error') {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  }

  async function handleSync() {
    setSyncing(true);
    try {
      const res = await api.harness.sync();
      if (res.success) {
        showToast('Sync complete', 'success');
      } else {
        showToast(`Sync failed: ${res.stderr || res.stdout}`, 'error');
      }
    } catch (err) {
      showToast(`Sync error: ${err instanceof Error ? err.message : String(err)}`, 'error');
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
        showToast(`Unsynced — ${count} item${count !== 1 ? 's' : ''} removed`, 'success');
      } else {
        showToast('Unsync failed', 'error');
      }
    } catch (err) {
      showToast(`Unsync error: ${err instanceof Error ? err.message : String(err)}`, 'error');
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
        <NavLink to="/evals" className={navClass}>Evals</NavLink>
        <NavLink to="/memory" className={navClass}>Memory</NavLink>
        <NavLink to="/plans" className={navClass}>Plans</NavLink>
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

      {toast && (
        <div className={`toast toast-${toast.type}`}>
          {toast.message}
        </div>
      )}
    </nav>
  );
}
