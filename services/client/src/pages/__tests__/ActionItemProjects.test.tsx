import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes, useNavigate } from 'react-router';
import { POLL_INTERVAL_MS } from '../../constants';
import { renderWithProviders } from '../../test-utils';
import { ActionItemsIndexPage } from '../ActionItemsIndexPage';
import { ActionItemDetailPage } from '../ActionItemDetailPage';
import { actionItem, deferred } from './actionItemFixture';
import { defaultView, mergeViewCookie } from '../../utils/viewPreferences';

vi.mock('../../api', async (original) => {
  const actual = await original<typeof import('../../api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      actionItems: {
        list: vi.fn(),
        get: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        remove: vi.fn(),
        move: vi.fn(),
      },
      actionItemProjects: { list: vi.fn(), create: vi.fn(), remove: vi.fn() },
    },
  };
});
import { api, ApiError } from '../../api';

const project = (id: number, name: string) => ({
  id,
  name,
  created_at: '2026-11-01T12:00:00Z',
});
let catalog: ReturnType<typeof project>[];
const rows = [
  actionItem(1),
  actionItem(2, { project: 'Other' }),
  actionItem(3, { project: null }),
];

function renderPage(path = '/action-items') {
  return renderWithProviders(
    <Routes>
      <Route path="/action-items" element={<ActionItemsIndexPage />} />
      <Route path="/action-items/new" element={<ActionItemDetailPage />} />
      <Route path="/action-items/:id" element={<ActionItemDetailPage />} />
    </Routes>,
    { initialEntries: [path] },
  );
}

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.resetAllMocks();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  catalog = [
    project(1, 'Work'),
    project(2, 'Other'),
    project(3, 'Unassigned'),
    project(4, 'All projects'),
  ];
  vi.mocked(api.actionItemProjects.list).mockImplementation(async () => ({
    items: [...catalog],
    total: catalog.length,
  }));
  vi.mocked(api.actionItemProjects.create).mockImplementation(async (name) => {
    const created = project(catalog.length + 1, name.trim());
    catalog.push(created);
    return created;
  });
  vi.mocked(api.actionItemProjects.remove).mockImplementation(async (id) => {
    catalog = catalog.filter((item) => item.id !== id);
    return { deleted: true, id };
  });
  vi.mocked(api.actionItems.list).mockImplementation(async (filters = {}) => {
    const selected = rows.filter(
      (item) =>
        (!filters.project || item.project === filters.project) &&
        (!filters.unassigned || item.project === null) &&
        (!filters.status ||
          filters.status === 'all' ||
          item.status === filters.status),
    );
    return { items: selected, total: selected.length };
  });
  vi.mocked(api.actionItems.get).mockImplementation(async (id) =>
    actionItem(id),
  );
  vi.mocked(api.actionItems.create).mockResolvedValue(actionItem(4));
  vi.mocked(api.actionItems.update).mockResolvedValue(
    actionItem(1, { revision: 2 }),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('first-class project navigation', () => {
  it('follows a renamed selected project by catalog identity after polling', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderPage('/action-items?project=Work');
    await screen.findByRole('tab', { name: 'Other' });
    await screen.findByText(rows[0].title);
    expect(
      screen.getByRole('link', { name: 'Manage projects' }),
    ).toHaveAttribute('href', '/projects');
    catalog = catalog.map((item) =>
      item.id === 1 ? { ...item, name: 'Renamed work' } : item,
    );
    catalog.push(project(8, 'Work'));
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ project: 'Renamed work' }),
      ),
    );
    expect(screen.getByRole('tab', { name: 'Renamed work' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tab', { name: 'Work' })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('keeps catalog tabs independent of status and tag filters', async () => {
    renderPage();
    const tabs = await screen.findByRole('tablist', {
      name: 'Action item projects',
    });
    expect(
      within(tabs).getByRole('tab', { name: 'All projects' }),
    ).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(within(tabs).getByRole('tab', { name: 'Work' }));
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ project: 'Work', offset: 0 }),
      ),
    );
    fireEvent.change(screen.getByLabelText('Tags'), {
      target: { value: 'security' },
    });
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ project: 'Work', tags: ['security'] }),
      ),
    );
    fireEvent.click(screen.getByRole('tab', { name: 'Completed' }));
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({
          status: 'completed',
          project: 'Work',
          tags: ['security'],
        }),
      ),
    );
    expect(within(tabs).getByRole('tab', { name: 'Other' })).toBeVisible();
    expect(within(tabs).getByRole('tab', { name: 'Work' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(api.actionItemProjects.list).toHaveBeenCalledTimes(1);
  });

  it('distinguishes the Unassigned only checkbox from real projects with navigation names', async () => {
    renderPage();
    const tabs = await screen.findByRole('tablist', {
      name: 'Action item projects',
    });
    expect(
      within(tabs).queryByRole('tab', { name: 'Unassigned' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Unassigned only' }));
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ unassigned: true, project: undefined }),
      ),
    );
    expect(await screen.findByRole('button', { name: 'Task 3' })).toBeVisible();
    fireEvent.click(
      within(tabs).getByRole('tab', { name: 'Project: Unassigned' }),
    );
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ project: 'Unassigned' }),
      ),
    );
    expect(
      vi.mocked(api.actionItems.list).mock.lastCall?.[0]?.unassigned,
    ).not.toBe(true);
    fireEvent.click(
      within(tabs).getByRole('tab', { name: 'Project: All projects' }),
    );
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ project: 'All projects' }),
      ),
    );
  });

  it('restores old Unassigned links under All projects and preserves the active tab and checkbox focus', async () => {
    renderPage('/action-items?unassigned=true');
    const all = await screen.findByRole('tab', {
      name: 'All projects',
    });
    const checkbox = screen.getByRole('checkbox', { name: 'Unassigned only' });
    expect(all).toHaveAttribute('aria-selected', 'true');
    expect(checkbox).toBeChecked();
    await userEvent.click(all);
    expect(all).toHaveFocus();
    expect(screen.getByRole('tab', { name: 'All projects' })).toBe(all);
    expect(checkbox).toBeChecked();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Work' })).toHaveFocus();
    expect(checkbox).not.toBeChecked();
    expect(checkbox).toBeDisabled();
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ project: 'Work' }),
      ),
    );
    await userEvent.keyboard('{Home}');
    expect(all).toHaveFocus();
    expect(all).toHaveAttribute('aria-selected', 'true');
    expect(checkbox).toBeEnabled();
    expect(checkbox).not.toBeChecked();
    await userEvent.click(checkbox);
    expect(checkbox).toHaveFocus();
    expect(all).toBe(screen.getByRole('tab', { name: 'All projects' }));
  });

  it('restores saved Unassigned filters and only resets pagination when toggled', async () => {
    document.cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      unassigned: true,
      status: 'completed',
      sort: 'title',
      tags: 'security',
      due_within_hours: 5,
      offset: 25,
      limit: 25,
    });
    renderPage();
    const checkbox = await screen.findByRole('checkbox', {
      name: 'Unassigned only',
    });
    expect(checkbox).toBeChecked();
    expect(screen.getByRole('tab', { name: 'All projects' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({
          unassigned: true,
          project: undefined,
          status: 'completed',
          sort: 'title',
          tags: ['security'],
          due_within_hours: 5,
          offset: 25,
          limit: 25,
        }),
      ),
    );
    await userEvent.click(checkbox);
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({
          project: undefined,
          status: 'completed',
          sort: 'title',
          tags: ['security'],
          due_within_hours: 5,
          offset: 0,
          limit: 25,
        }),
      ),
    );
    expect(
      vi.mocked(api.actionItems.list).mock.lastCall?.[0]?.unassigned,
    ).not.toBe(true);
    expect(screen.getByLabelText('Tags')).toHaveValue('security');
    expect(screen.getByLabelText('Hours')).toHaveValue(5);
  });

  it('normalizes a conflicting legacy URL to its named project', async () => {
    renderPage('/action-items?project=Work&unassigned=true');
    expect(await screen.findByRole('tab', { name: 'Work' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    const checkbox = screen.getByRole('checkbox', { name: 'Unassigned only' });
    expect(checkbox).not.toBeChecked();
    expect(checkbox).toBeDisabled();
    expect(checkbox).toHaveAttribute(
      'title',
      'Select All projects to filter unassigned items.',
    );
    expect(
      vi.mocked(api.actionItems.list).mock.lastCall?.[0]?.unassigned,
    ).not.toBe(true);
  });

  it('creates an empty project, selects it and retains it after reload', async () => {
    const rendered = renderPage();
    await screen.findByRole('tab', { name: 'Work' });
    fireEvent.click(screen.getByRole('button', { name: 'New project' }));
    fireEvent.change(screen.getByLabelText('Project name'), {
      target: { value: '  New group  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create project' }));
    expect(
      await screen.findByRole('tab', { name: 'New group' }),
    ).toHaveAttribute('aria-selected', 'true');
    expect(api.actionItemProjects.create).toHaveBeenCalledWith('New group');
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ project: 'New group', offset: 0 }),
      ),
    );
    expect(screen.getByText('No open action items found.')).toBeVisible();
    rendered.unmount();
    renderPage();
    expect(
      await screen.findByRole('tab', { name: 'New group' }),
    ).toHaveAttribute('aria-selected', 'true');
  });

  it.each(['   ', 'x'.repeat(201), 'bad\tname', '\u0001name'])(
    'rejects invalid new names without writing the catalog: %j',
    async (name) => {
      renderPage();
      await screen.findByRole('tab', { name: 'Work' });
      fireEvent.click(screen.getByRole('button', { name: 'New project' }));
      fireEvent.change(screen.getByLabelText('Project name'), {
        target: { value: name },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Create project' }));
      expect(await screen.findByRole('alert')).toHaveTextContent(
        /project name/i,
      );
      expect(api.actionItemProjects.create).not.toHaveBeenCalled();
    },
  );

  it('retains task access and selected names when catalog loading fails, then retries', async () => {
    vi.mocked(api.actionItemProjects.list).mockRejectedValueOnce(
      new Error('Catalog unavailable'),
    );
    renderPage('/action-items?project=Work');
    expect(await screen.findByRole('button', { name: 'Task 1' })).toBeVisible();
    expect(await screen.findByRole('tab', { name: 'Work' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(await screen.findByRole('alert')).toHaveTextContent(/projects/i);
    fireEvent.click(screen.getByRole('button', { name: 'Retry projects' }));
    expect(await screen.findByRole('tab', { name: 'Other' })).toBeVisible();
    expect(screen.getByRole('tab', { name: 'Work' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('reports referenced-project delete errors and only clears selection after success', async () => {
    vi.mocked(api.actionItemProjects.remove).mockRejectedValueOnce(
      new ApiError('Project has task history', 409),
    );
    renderPage('/action-items?project=Work');
    await screen.findByRole('tab', { name: 'Work' });
    fireEvent.click(screen.getByRole('button', { name: 'Delete project' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Project has task history',
    );
    expect(screen.getByRole('tab', { name: 'Work' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Delete project' }));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'All projects' })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    );
    expect(api.actionItemProjects.remove).toHaveBeenCalledWith(1);
  });

  it('keeps all fifty project groups keyboard reachable', async () => {
    catalog = Array.from({ length: 50 }, (_, index) =>
      project(index + 1, 'Group ' + String(index + 1).padStart(2, '0')),
    );
    renderPage();
    const tabs = await screen.findByRole('tablist', {
      name: 'Action item projects',
    });
    await waitFor(() =>
      expect(within(tabs).getAllByRole('tab')).toHaveLength(51),
    );
    within(tabs).getByRole('tab', { name: 'All projects' }).focus();
    await userEvent.keyboard('{End}');
    expect(within(tabs).getByRole('tab', { name: 'Group 50' })).toHaveFocus();
    expect(within(tabs).getByRole('tab', { name: 'Group 50' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('never commits a deferred prior project response into the new scope', async () => {
    const old = deferred<{ items: typeof rows; total: number }>();
    renderPage();
    const tabs = await screen.findByRole('tablist', {
      name: 'Action item projects',
    });
    vi.mocked(api.actionItems.list)
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce({ items: [rows[1]], total: 1 });
    fireEvent.click(within(tabs).getByRole('tab', { name: 'Work' }));
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ project: 'Work' }),
      ),
    );
    fireEvent.click(within(tabs).getByRole('tab', { name: 'Other' }));
    await screen.findByRole('button', { name: 'Task 2' });
    await act(async () => {
      old.resolve({ items: [rows[0]], total: 1 });
    });
    expect(
      screen.queryByRole('button', { name: 'Task 1' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Task 2' })).toBeVisible();
  });

  it('polls the catalog at the shared interval and pauses while its creation form is a draft', async () => {
    vi.useFakeTimers();
    await act(async () => {
      renderPage();
    });
    expect(api.actionItemProjects.list).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS - 1);
    });
    expect(api.actionItemProjects.list).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(api.actionItemProjects.list).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: 'New project' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    });
    expect(api.actionItemProjects.list).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    });
    expect(api.actionItemProjects.list).toHaveBeenCalledTimes(3);
  });

  it('does not replace a later URL scope when an earlier project creation completes', async () => {
    const created = deferred<ReturnType<typeof project>>();
    vi.mocked(api.actionItemProjects.create).mockReturnValueOnce(
      created.promise,
    );
    function ScopeSwitch() {
      const navigate = useNavigate();
      return (
        <button onClick={() => navigate('/action-items?project=Other')}>
          Change route scope
        </button>
      );
    }
    renderWithProviders(
      <>
        <ScopeSwitch />
        <Routes>
          <Route path="/action-items" element={<ActionItemsIndexPage />} />
        </Routes>
      </>,
      { initialEntries: ['/action-items?project=Work'] },
    );
    await screen.findByRole('tab', { name: 'Work' });
    fireEvent.click(screen.getByRole('button', { name: 'New project' }));
    fireEvent.change(screen.getByLabelText('Project name'), {
      target: { value: 'Created later' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create project' }));
    await waitFor(() =>
      expect(api.actionItemProjects.create).toHaveBeenCalledTimes(1),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Change route scope' }));
    expect(screen.getByRole('tab', { name: 'Other' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await act(async () => {
      const saved = project(9, 'Created later');
      catalog.push(saved);
      created.resolve(saved);
    });
    expect(
      await screen.findByRole('tab', { name: 'Created later' }),
    ).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByRole('tab', { name: 'Other' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });
});

describe('project assignment drafts', () => {
  it('retains a selected project and draft while the picker catalog fails and retries', async () => {
    vi.mocked(api.actionItemProjects.list).mockRejectedValueOnce(
      new Error('Catalog unavailable'),
    );
    renderPage('/action-items/new?project=Work');
    const picker = await screen.findByRole('combobox', { name: 'Project' });
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Retained draft' },
    });
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Your selection is retained',
    );
    expect(picker).toHaveValue('Work');
    fireEvent.click(screen.getByRole('button', { name: 'Retry projects' }));
    await screen.findByRole('option', { name: 'Other' });
    expect(picker).toHaveValue('Work');
    expect(screen.getByLabelText('Title')).toHaveValue('Retained draft');
  });
  it('defaults a new task from its selected project using URL-safe names', async () => {
    const name = 'Café / QA & family #1';
    catalog.push(project(7, name));
    renderPage('/action-items?' + new URLSearchParams({ project: name }));
    await screen.findByRole('tab', { name });
    fireEvent.click(screen.getByRole('link', { name: 'New action item' }));
    expect(
      await screen.findByRole('combobox', { name: 'Project' }),
    ).toHaveValue(name);
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Scoped task' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.actionItems.create).toHaveBeenCalledWith(
        expect.objectContaining({
          project: name,
          request_id: expect.any(String),
        }),
      ),
    );
  });

  it('does not reseed a changed draft when a delayed catalog arrives', async () => {
    const catalogRead = deferred<{ items: typeof catalog; total: number }>();
    vi.mocked(api.actionItemProjects.list).mockReturnValueOnce(
      catalogRead.promise,
    );
    renderPage('/action-items/new?project=Work');
    const picker = await screen.findByRole('combobox', { name: 'Project' });
    expect(picker).toHaveValue('Work');
    fireEvent.change(picker, { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Keep this draft' },
    });
    await act(async () => {
      catalogRead.resolve({ items: catalog, total: catalog.length });
    });
    expect(picker).toHaveValue('');
    expect(screen.getByLabelText('Title')).toHaveValue('Keep this draft');
  });

  it('preserves exact legacy project values through unrelated edits', async () => {
    const name = '  Legacy\nproject  ';
    catalog.push(project(8, name));
    vi.mocked(api.actionItems.get).mockResolvedValue(
      actionItem(1, { project: name }),
    );
    renderPage('/action-items/1?edit=1');
    expect(
      await screen.findByRole('combobox', { name: 'Project' }),
    ).toHaveValue(name);
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Title update only' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.actionItems.update).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ project: name, expected_revision: 1 }),
      ),
    );
  });

  it('keeps uncertain creation frozen to its original project and UUID', async () => {
    vi.mocked(api.actionItems.create).mockRejectedValueOnce(
      new Error('Uncertain save'),
    );
    renderPage('/action-items/new?project=Work');
    const picker = await screen.findByRole('combobox', { name: 'Project' });
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Frozen task' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByRole('alert');
    const original = vi.mocked(api.actionItems.create).mock.calls[0][0];
    expect(picker).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.actionItems.create).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(api.actionItems.create).mock.calls[1][0]).toEqual(
      original,
    );
    expect(original.project).toBe('Work');
  });
});

it('restores a selected project and preserves independent saved status and tags', async () => {
  document.cookie = mergeViewCookie('', 'actionItems', {
    ...defaultView('actionItems'),
    project: 'Work',
    status: 'completed',
    sort: 'title',
    tags: 'security',
    offset: 25,
    limit: 25,
  });
  renderPage();
  expect(await screen.findByRole('tab', { name: 'Work' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  expect(api.actionItems.list).toHaveBeenCalledWith(
    expect.objectContaining({
      project: 'Work',
      status: 'completed',
      tags: ['security'],
      offset: 25,
    }),
  );
});
