import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router';
import userEvent from '@testing-library/user-event';
import { Sidebar } from '../Sidebar';

declare const jsdom: { window: { localStorage: Storage } };

const mockNotify = vi.fn();

vi.mock('../../api', () => ({
  api: {
    harness: {
      sync: vi.fn(),
      unsync: vi.fn(),
    },
  },
}));

vi.mock('../../context/useNotification', () => ({
  useNotification: () => ({ notify: mockNotify }),
}));

import { api } from '../../api';

function renderSidebar(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // Node's experimental global storage must not shadow the jsdom browser store.
  vi.stubGlobal('localStorage', jsdom.window.localStorage);
  window.localStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Sidebar', () => {
  it('renders title', () => {
    renderSidebar();
    expect(screen.getByText('Agent Smith')).toBeInTheDocument();
  });

  it('renders all navigation links', () => {
    renderSidebar();
    for (const label of [
      'Action items',
      'Agents',
      'Hooks',
      'Rules',
      'Skills',
      'Tools',
      'Audit',
      'Evals',
      'Jobs',
      'Proposals',
      'Results',
      'Chat',
      'Meetings',
      'Memory',
      'Plans',
      'Profiles',
      'Projects',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('keeps Profiles active while a profile is open', () => {
    renderSidebar('/profiles/profile-id');
    const link = screen.getByRole('link', { name: 'Profiles' });
    expect(link).toHaveAttribute('href', '/profiles');
    expect(link).toHaveClass('active');
    expect(screen.getByRole('link', { name: 'Meetings' })).not.toHaveClass(
      'active',
    );
  });

  it('orders named groups by workspace, harness and operations, retaining all 18 alphabetized links', () => {
    renderSidebar();
    expect(
      screen
        .getAllByRole('heading', { level: 2 })
        .map((heading) => heading.textContent?.replace('›', '')),
    ).toEqual(['Workspace', 'Harness', 'Operations']);
    const sections = screen.getAllByRole('region').map((section) =>
      within(section)
        .queryAllByRole('link')
        .map((link) => link.textContent),
    );
    expect(sections).toEqual([
      [
        'Action items',
        'Chat',
        'Costs',
        'Meetings',
        'Plans',
        'Profiles',
        'Projects',
      ],
      ['Agents', 'Hooks', 'Memory', 'Rules', 'Skills', 'Tools'],
      ['Audit', 'Evals', 'Jobs', 'Proposals', 'Results'],
    ]);
    expect(screen.getAllByRole('link')).toHaveLength(18);
  });

  it('supports mouse, Enter and Space disclosure while removing collapsed links from keyboard navigation', async () => {
    const user = userEvent.setup();
    renderSidebar();
    const toggle = screen.getByRole('button', { name: 'Harness' });
    const panel = document.getElementById(
      toggle.getAttribute('aria-controls')!,
    );
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(panel).toHaveAttribute('hidden');
    expect(
      screen.queryByRole('link', { name: 'Rules' }),
    ).not.toBeInTheDocument();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('link', { name: 'Rules' })).toBeVisible();
    await user.keyboard(' ');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.tab();
    expect(screen.getByRole('button', { name: 'Operations' })).toHaveFocus();
  });

  it('restores collapsed groups across remounts while opening the current route group', () => {
    const first = renderSidebar('/action-items');
    fireEvent.click(screen.getByRole('button', { name: 'Operations' }));
    expect(
      JSON.parse(window.localStorage.getItem('agent-smith.sidebar.v1')!),
    ).toEqual({ version: 1, collapsed: ['maintenance'] });
    first.unmount();
    renderSidebar('/profiles/profile-id');
    expect(screen.getByRole('button', { name: 'Operations' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(screen.getByRole('button', { name: 'Workspace' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByRole('link', { name: 'Profiles' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it.each([
    ['/harness/rule/83', 'Rules'],
    ['/memory', 'Memory'],
  ])(
    'opens initially collapsed destination %s without forcing other groups open',
    (path, label) => {
      window.localStorage.setItem(
        'agent-smith.sidebar.v1',
        JSON.stringify({
          version: 1,
          collapsed: ['external', 'harness', 'maintenance'],
        }),
      );
      renderSidebar(path);
      expect(screen.getByRole('button', { name: 'Harness' })).toHaveAttribute(
        'aria-expanded',
        'true',
      );
      expect(screen.getByRole('button', { name: 'Workspace' })).toHaveAttribute(
        'aria-expanded',
        'false',
      );
      expect(
        screen.getByRole('button', { name: 'Operations' }),
      ).toHaveAttribute('aria-expanded', 'false');
      expect(screen.getByRole('link', { name: label })).toHaveClass('active');
      expect(screen.getByRole('link', { name: label })).toHaveAttribute(
        'aria-current',
        'page',
      );
      expect(
        JSON.parse(window.localStorage.getItem('agent-smith.sidebar.v1')!),
      ).toEqual({ version: 1, collapsed: ['external', 'maintenance'] });
    },
  );

  it('opens route destinations and allows the active group to be collapsed manually afterwards', () => {
    function RouteControls() {
      const navigate = useNavigate();
      return (
        <>
          <button onClick={() => navigate('/harness/rule/83')}>
            Open rule
          </button>
          <button onClick={() => navigate('/harness/hook/new')}>
            New hook
          </button>
          <button onClick={() => navigate('/memory')}>Open memory</button>
          <button onClick={() => navigate('/jobs/1')}>Open job</button>
        </>
      );
    }
    render(
      <MemoryRouter initialEntries={['/profiles/profile-id']}>
        <Sidebar />
        <RouteControls />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Harness' }));
    fireEvent.click(screen.getByRole('button', { name: 'Operations' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open rule' }));
    expect(screen.getByRole('link', { name: 'Rules' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Harness' }));
    expect(
      screen.queryByRole('link', { name: 'Rules' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'New hook' }));
    expect(screen.getByRole('link', { name: 'Hooks' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Harness' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open memory' }));
    expect(screen.getByRole('link', { name: 'Memory' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Open job' }));
    expect(screen.getByRole('link', { name: 'Jobs' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it.each([
    'not-json',
    '{"version":2,"collapsed":["harness"]}',
    '{"version":1,"collapsed":"harness"}',
    '{"version":1,"collapsed":["unknown"]}',
  ])('ignores malformed or incompatible stored preferences: %s', (stored) => {
    window.localStorage.setItem('agent-smith.sidebar.v1', stored);
    renderSidebar();
    for (const name of ['Workspace', 'Harness', 'Operations']) {
      expect(screen.getByRole('button', { name })).toHaveAttribute(
        'aria-expanded',
        'true',
      );
    }
  });

  it('keeps disclosure usable when browser storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('Storage denied', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage denied', 'SecurityError');
    });
    renderSidebar();
    const toggle = screen.getByRole('button', { name: 'Workspace' });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(screen.getByRole('link', { name: 'Action items' })).toBeVisible();
  });

  it('keeps deployment actions outside the scrolling navigation region', () => {
    const { container } = renderSidebar();
    const scrolling = container.querySelector('.sidebar-navigation');
    const footer = container.querySelector('.sidebar-footer');
    expect(scrolling?.contains(footer)).toBe(false);
    expect(footer?.contains(screen.getByRole('button', { name: 'Sync' }))).toBe(
      true,
    );
    expect(
      footer?.contains(screen.getByRole('button', { name: 'Unsync' })),
    ).toBe(true);
  });

  it.each(['sync', 'unsync'] as const)(
    'locks both deployment actions while %s waits without locking navigation',
    async (action) => {
      let finish!: (result: {
        success: boolean;
        stdout: string;
        stderr: string;
        removed: string[];
      }) => void;
      const response = new Promise<{
        success: boolean;
        stdout: string;
        stderr: string;
        removed: string[];
      }>((resolve) => {
        finish = resolve;
      });
      vi.mocked(api.harness[action]).mockReturnValueOnce(response);
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      renderSidebar();
      fireEvent.click(
        screen.getByRole('button', {
          name: action === 'sync' ? 'Sync' : 'Unsync',
        }),
      );
      expect(
        screen.getByRole('button', { name: /^(Sync|Syncing\.\.\.)$/ }),
      ).toBeDisabled();
      expect(
        screen.getByRole('button', { name: /^(Unsync|Unsyncing\.\.\.)$/ }),
      ).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Workspace' })).toBeEnabled();
      fireEvent.click(
        screen.getByRole('button', {
          name: action === 'sync' ? 'Unsync' : 'Sync',
        }),
      );
      expect(
        api.harness[action === 'sync' ? 'unsync' : 'sync'],
      ).not.toHaveBeenCalled();
      finish({ success: true, stdout: '', stderr: '', removed: [] });
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Sync' })).toBeEnabled(),
      );
      expect(screen.getByRole('button', { name: 'Unsync' })).toBeEnabled();
    },
  );

  it('sync success notifies user', async () => {
    vi.mocked(api.harness.sync).mockResolvedValue({
      success: true,
      stdout: '',
      stderr: '',
    });
    renderSidebar();
    fireEvent.click(screen.getByText('Sync'));
    await waitFor(() =>
      expect(mockNotify).toHaveBeenCalledWith('Sync complete', 'success'),
    );
  });

  it('sync failure notifies with error', async () => {
    vi.mocked(api.harness.sync).mockResolvedValue({
      success: false,
      stdout: '',
      stderr: 'boom',
    });
    renderSidebar();
    fireEvent.click(screen.getByText('Sync'));
    await waitFor(() =>
      expect(mockNotify).toHaveBeenCalledWith('Sync failed: boom', 'error'),
    );
  });

  it('sync exception notifies with error', async () => {
    vi.mocked(api.harness.sync).mockRejectedValue(new Error('network'));
    renderSidebar();
    fireEvent.click(screen.getByText('Sync'));
    await waitFor(() =>
      expect(mockNotify).toHaveBeenCalledWith('Sync error: network', 'error'),
    );
  });

  it('unsync requires confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderSidebar();
    fireEvent.click(screen.getByText('Unsync'));
    expect(api.harness.unsync).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it('unsync success notifies with count', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(api.harness.unsync).mockResolvedValue({
      success: true,
      removed: ['/a', '/b'],
    });
    renderSidebar();
    fireEvent.click(screen.getByText('Unsync'));
    await waitFor(() =>
      expect(mockNotify).toHaveBeenCalledWith(
        'Unsynced — 2 items removed',
        'success',
      ),
    );
    vi.restoreAllMocks();
  });
});
