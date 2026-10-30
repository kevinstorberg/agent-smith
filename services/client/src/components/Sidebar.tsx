import { useState } from 'react';
import { NavLink } from 'react-router';
import { api } from '../api';
import { useNotification } from '../context/useNotification';

// Separate deployable harness configuration from its management tools and general-purpose resources.
// Group names stay internal; the sidebar uses separators without headings.
const NAV_SECTIONS = [{ id: 'harness', links: [
  { path: '/harness/agents', label: 'Agents' },
  { path: '/harness/hooks', label: 'Hooks' },
  { path: '/harness/rules', label: 'Rules' },
  { path: '/harness/skills', label: 'Skills' },
  { path: '/harness/tools', label: 'Tools' },
] }, { id: 'maintenance', links: [
  { path: '/audit', label: 'Audit' },
  { path: '/eval-configs', label: 'Evals' },
  { path: '/jobs', label: 'Jobs' },
  { path: '/proposals', label: 'Proposals' },
  { path: '/evals', label: 'Results' },
] }, { id: 'external', links: [
  { path: '/action-items', label: 'Action items' },
  { path: '/chat', label: 'Chat' },
  { path: '/meetings', label: 'Meetings' },
  { path: '/memory', label: 'Memory' },
  { path: '/plans', label: 'Plans' },
  { path: '/profiles', label: 'Profiles' },
] }];

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

      {NAV_SECTIONS.map(section => <div className="sidebar-section" key={section.id}>
        {[...section.links].sort((left, right) => left.label.localeCompare(right.label)).map(link => (
          <NavLink key={link.path} to={link.path} className={navClass}>{link.label}</NavLink>
        ))}
      </div>)}

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
