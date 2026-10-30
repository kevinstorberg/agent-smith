import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { Sidebar } from '../Sidebar';

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
});

describe('Sidebar', () => {
  it('renders title', () => {
    renderSidebar();
    expect(screen.getByText('Agent Smith')).toBeInTheDocument();
  });

  it('renders all navigation links', () => {
    renderSidebar();
    for (const label of ['Agents', 'Hooks', 'Rules', 'Skills', 'Tools', 'Audit', 'Evals', 'Jobs', 'Proposals', 'Results', 'Chat', 'Meetings', 'Memory', 'Plans', 'Profiles']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('keeps Profiles active while a profile is open', () => {
    renderSidebar('/profiles/profile-id');
    const link = screen.getByRole('link', { name: 'Profiles' });
    expect(link).toHaveAttribute('href', '/profiles');
    expect(link).toHaveClass('active');
    expect(screen.getByRole('link', { name: 'Meetings' })).not.toHaveClass('active');
  });

  it('alphabetizes links within the three unlabeled functional groups', () => {
    const { container } = renderSidebar();
    const sections = [...container.querySelectorAll('.sidebar-section')].map(section => within(section as HTMLElement).queryAllByRole('link').map(link => link.textContent));
    expect(sections).toEqual([
      ['Agents', 'Hooks', 'Rules', 'Skills', 'Tools'],
      ['Audit', 'Evals', 'Jobs', 'Proposals', 'Results'],
      ['Action items', 'Chat', 'Meetings', 'Memory', 'Plans', 'Profiles'],
      [],
    ]);
  });

  it('sync success notifies user', async () => {
    vi.mocked(api.harness.sync).mockResolvedValue({ success: true, stdout: '', stderr: '' });
    renderSidebar();
    fireEvent.click(screen.getByText('Sync'));
    await waitFor(() => expect(mockNotify).toHaveBeenCalledWith('Sync complete', 'success'));
  });

  it('sync failure notifies with error', async () => {
    vi.mocked(api.harness.sync).mockResolvedValue({ success: false, stdout: '', stderr: 'boom' });
    renderSidebar();
    fireEvent.click(screen.getByText('Sync'));
    await waitFor(() => expect(mockNotify).toHaveBeenCalledWith('Sync failed: boom', 'error'));
  });

  it('sync exception notifies with error', async () => {
    vi.mocked(api.harness.sync).mockRejectedValue(new Error('network'));
    renderSidebar();
    fireEvent.click(screen.getByText('Sync'));
    await waitFor(() => expect(mockNotify).toHaveBeenCalledWith('Sync error: network', 'error'));
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
    vi.mocked(api.harness.unsync).mockResolvedValue({ success: true, removed: ['/a', '/b'] });
    renderSidebar();
    fireEvent.click(screen.getByText('Unsync'));
    await waitFor(() => expect(mockNotify).toHaveBeenCalledWith('Unsynced — 2 items removed', 'success'));
    vi.restoreAllMocks();
  });
});
