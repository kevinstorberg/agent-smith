import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { Link, NavLink, useLocation } from 'react-router';
import { api } from '../api';
import { TYPE_PATHS } from '../constants';
import { useNotification } from '../context/useNotification';

const NAV_SECTIONS = [
  {
    id: 'external',
    label: 'Workspace',
    links: [
      { path: '/action-items', label: 'Action items' },
      { path: '/chat', label: 'Chat' },
      { path: '/meetings', label: 'Meetings' },
      { path: '/plans', label: 'Plans' },
      { path: '/profiles', label: 'Profiles' },
    ],
  },
  {
    id: 'harness',
    label: 'Harness',
    links: [
      { path: '/harness/agents', label: 'Agents' },
      { path: '/harness/hooks', label: 'Hooks' },
      { path: '/memory', label: 'Memory' },
      { path: '/harness/rules', label: 'Rules' },
      { path: '/harness/skills', label: 'Skills' },
      { path: '/harness/tools', label: 'Tools' },
    ],
  },
  {
    id: 'maintenance',
    label: 'Operations',
    links: [
      { path: '/audit', label: 'Audit' },
      { path: '/eval-configs', label: 'Evals' },
      { path: '/jobs', label: 'Jobs' },
      { path: '/proposals', label: 'Proposals' },
      { path: '/evals', label: 'Results' },
    ],
  },
] as const;

type SectionId = (typeof NAV_SECTIONS)[number]['id'];
const STORAGE_KEY = 'agent-smith.sidebar.v1';

function isSectionId(value: unknown): value is SectionId {
  return NAV_SECTIONS.some((section) => section.id === value);
}

function readCollapsedSections(): SectionId[] {
  try {
    const saved: unknown = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) || 'null',
    );
    if (
      saved &&
      typeof saved === 'object' &&
      !Array.isArray(saved) &&
      'version' in saved &&
      saved.version === 1 &&
      'collapsed' in saved &&
      Array.isArray(saved.collapsed) &&
      saved.collapsed.every(isSectionId)
    ) {
      return [...new Set(saved.collapsed)];
    }
  } catch {
    return [];
  }
  return [];
}

function containsRoute(path: string, route: string): boolean {
  return path === route || path.startsWith(`${route}/`);
}

function navClass({ isActive }: { isActive: boolean }): string {
  return `sidebar-link${isActive ? ' active' : ''}`;
}

export function Sidebar() {
  const { pathname } = useLocation();
  const harnessType = Object.keys(TYPE_PATHS).find((type) =>
    containsRoute(pathname, `/harness/${type}`),
  );
  const activeAlias = harnessType
    ? `/harness/${TYPE_PATHS[harnessType]}`
    : null;
  const activeSection = NAV_SECTIONS.find((section) =>
    section.links.some(
      (link) => containsRoute(pathname, link.path) || activeAlias === link.path,
    ),
  )?.id;
  const [collapsed, setCollapsed] = useState<SectionId[]>(() =>
    readCollapsedSections().filter((id) => id !== activeSection),
  );
  const [navigationOpen, setNavigationOpen] = useState(false);
  const navigationToggle = useRef<HTMLButtonElement>(null);
  const [syncing, setSyncing] = useState(false);
  const [unsyncing, setUnsyncing] = useState(false);
  const busy = syncing || unsyncing;
  const { notify } = useNotification();

  useEffect(() => {
    if (activeSection)
      setCollapsed((previous) =>
        previous.includes(activeSection)
          ? previous.filter((id) => id !== activeSection)
          : previous,
      );
  }, [pathname, activeSection]);
  useEffect(() => {
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ version: 1, collapsed }),
      );
    } catch {
      return;
    }
  }, [collapsed]);

  useEffect(() => {
    setNavigationOpen(false);
  }, [pathname]);

  function followNavigation(event: MouseEvent<HTMLAnchorElement>) {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    setNavigationOpen(false);
    requestAnimationFrame(() =>
      document.getElementById('main-content')?.focus(),
    );
  }

  async function handleSync() {
    if (busy) return;
    setSyncing(true);
    try {
      const res = await api.harness.sync();
      if (res.success) {
        notify('Sync complete', 'success');
      } else {
        notify(`Sync failed: ${res.stderr || res.stdout}`, 'error');
      }
    } catch (err) {
      notify(
        `Sync error: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    } finally {
      setSyncing(false);
    }
  }

  async function handleUnsync() {
    if (busy) return;
    if (!confirm('Remove all synced agent files?')) return;
    setUnsyncing(true);
    try {
      const res = await api.harness.unsync();
      if (res.success) {
        const count = res.removed?.length || 0;
        notify(
          `Unsynced — ${count} item${count !== 1 ? 's' : ''} removed`,
          'success',
        );
      } else {
        notify('Unsync failed', 'error');
      }
    } catch (err) {
      notify(
        `Unsync error: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
    } finally {
      setUnsyncing(false);
    }
  }

  return (
    <nav
      className="sidebar"
      aria-label="Primary navigation"
      onKeyDown={(event) => {
        if (event.key === 'Escape' && navigationOpen) {
          event.preventDefault();
          setNavigationOpen(false);
          navigationToggle.current?.focus();
        }
      }}
    >
      <div className="sidebar-header">
        <img
          src="/agent_smith_logo.svg"
          alt="Agent Smith"
          className="sidebar-logo"
        />
        <div className="sidebar-title">Agent Smith</div>
        <button
          type="button"
          ref={navigationToggle}
          className="btn btn-sm sidebar-menu-toggle"
          aria-expanded={navigationOpen}
          aria-controls="sidebar-menu"
          onClick={() => setNavigationOpen((previous) => !previous)}
        >
          {navigationOpen ? 'Close menu' : 'Menu'}
        </button>
      </div>

      <div
        className={`sidebar-body${navigationOpen ? ' is-open' : ''}`}
        id="sidebar-menu"
      >
        <div className="sidebar-navigation">
          {NAV_SECTIONS.map((section) => (
            <section
              className="sidebar-section"
              key={section.id}
              aria-labelledby={`sidebar-toggle-${section.id}`}
            >
              <h2 className="sidebar-section-heading">
                <button
                  type="button"
                  className="sidebar-section-toggle"
                  id={`sidebar-toggle-${section.id}`}
                  aria-expanded={!collapsed.includes(section.id)}
                  aria-controls={`sidebar-links-${section.id}`}
                  onClick={() =>
                    setCollapsed((previous) =>
                      previous.includes(section.id)
                        ? previous.filter((id) => id !== section.id)
                        : [...previous, section.id],
                    )
                  }
                >
                  {section.label}
                  <span className="sidebar-section-chevron" aria-hidden="true">
                    ›
                  </span>
                </button>
              </h2>
              <div
                className="sidebar-section-links"
                id={`sidebar-links-${section.id}`}
                hidden={collapsed.includes(section.id)}
              >
                {[...section.links]
                  .sort((left, right) => left.label.localeCompare(right.label))
                  .map((link) =>
                    activeAlias === link.path ? (
                      <Link
                        key={link.path}
                        to={link.path}
                        onClick={followNavigation}
                        className={navClass({ isActive: true })}
                        aria-current="page"
                      >
                        {link.label}
                      </Link>
                    ) : (
                      <NavLink
                        key={link.path}
                        to={link.path}
                        onClick={followNavigation}
                        className={navClass}
                      >
                        {link.label}
                      </NavLink>
                    ),
                  )}
              </div>
            </section>
          ))}
        </div>

        <div className="sidebar-footer">
          <div className="sidebar-actions">
            <button
              type="button"
              onClick={handleSync}
              disabled={busy}
              className="sidebar-btn"
            >
              {syncing ? 'Syncing...' : 'Sync'}
            </button>
            <button
              type="button"
              onClick={handleUnsync}
              disabled={busy}
              className="sidebar-btn sidebar-btn-danger"
            >
              {unsyncing ? 'Unsyncing...' : 'Unsync'}
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}
