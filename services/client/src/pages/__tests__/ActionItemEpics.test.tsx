import { findActionButton } from './actionItemControls';
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, type ActionItemEpic } from '../../api';
import { ActionItemsIndexPage } from '../ActionItemsIndexPage';
import { renderWithProviders } from '../../test-utils';
import { actionItem, deferred } from './actionItemFixture';
import { epicGroup, queuePage } from './actionItemEpicFixture';

vi.mock('../../api', async (original) => {
  const actual = await original<typeof import('../../api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      actionItems: {
        ...actual.api.actionItems,
        get: vi.fn(),
        update: vi.fn(),
        remove: vi.fn(),
      },
      actionItemProjects: { list: vi.fn() },
      actionItemQueue: { list: vi.fn(), move: vi.fn(), setEpic: vi.fn() },
      actionItemEpics: {
        list: vi.fn(),
        create: vi.fn(),
        rename: vi.fn(),
        remove: vi.fn(),
      },
    },
  };
});

beforeEach(() => {
  vi.resetAllMocks();
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.mocked(api.actionItemProjects.list).mockResolvedValue({
    items: [],
    total: 0,
  });
  vi.mocked(api.actionItemQueue.list).mockResolvedValue({
    items: [epicGroup()],
    total: 1,
    matching_count: 1,
  });
  vi.mocked(api.actionItemEpics.list).mockResolvedValue({
    items: [epicGroup().epic],
  });
  vi.mocked(api.actionItemQueue.move).mockResolvedValue({ saved: true });
  vi.mocked(api.actionItemQueue.setEpic).mockResolvedValue(actionItem(2));
  vi.mocked(api.actionItemEpics.remove).mockResolvedValue({
    deleted: true,
    id: 10,
  });
});

describe('saved Action Item Epics', () => {
  it('uses one visible sort header and sorts children without changing Epic membership', async () => {
    const members = [
      actionItem(2, {
        title: 'Zulu work',
        due_at: '2026-12-01T14:00:00Z',
        updated_at: '2026-11-24T12:00:00Z',
      }),
      actionItem(3, {
        title: 'Alpha work',
        updated_at: '2026-11-25T12:00:00Z',
      }),
    ];
    vi.mocked(api.actionItemQueue.list).mockImplementation(async (filters) => {
      const children = [...members].sort((left, right) =>
        filters?.sort === 'title'
          ? left.title.localeCompare(right.title)
          : filters?.sort === 'updated'
            ? right.updated_at.localeCompare(left.updated_at)
            : left.updated_at.localeCompare(right.updated_at),
      );
      return {
        items: [
          epicGroup(10, children),
          ...queuePage({ items: [actionItem(4)], total: 1 }).items,
        ],
        total: 2,
        matching_count: 3,
      };
    });
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items'],
    });
    const region = await screen.findByRole('region', { name: 'Epic Release' });
    const table = within(region).getByRole('table', {
      name: 'Action items in Epic Release',
    });
    const currentTable = () =>
      screen.getByRole('table', { name: 'Action items in Epic Release' });
    const titles = () =>
      within(currentTable())
        .getAllByRole('button', { name: /^(Zulu|Alpha) work$/ })
        .map((button) => button.textContent?.replace(/^[⌄›]/, ''));
    expect(screen.getByRole('button', { name: 'Due date' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Updated' })).toBeVisible();
    const zulu = within(table)
      .getByRole('button', { name: 'Zulu work' })
      .closest('tr')!;
    expect(zulu.querySelector('.action-due-cell')).toHaveTextContent(
      'December',
    );
    expect(zulu.querySelector('.action-updated-cell')).toHaveTextContent(
      'Nov 24',
    );

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Title' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Title' }));
    await waitFor(() =>
      expect(api.actionItemQueue.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'title' }),
      ),
    );
    await waitFor(() => expect(titles()).toEqual(['Alpha work', 'Zulu work']));
    fireEvent.click(screen.getByRole('button', { name: 'Updated' }));
    await waitFor(() =>
      expect(api.actionItemQueue.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'updated' }),
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Updated' }));
    await waitFor(() => expect(titles()).toEqual(['Zulu work', 'Alpha work']));
    expect(api.actionItemQueue.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort: 'updated_asc' }),
    );
    expect(
      screen.getByRole('button', { name: 'Task 4' }).closest('section'),
    ).toBeNull();
    expect(api.actionItemQueue.move).not.toHaveBeenCalled();
    expect(api.actionItemQueue.setEpic).not.toHaveBeenCalled();
    expect(api.actionItems.update).not.toHaveBeenCalled();
  });

  it('counts root groups separately and displays complete matching children with their sibling ranks', async () => {
    const group = epicGroup(10, [
      actionItem(2, { priority: 77 }),
      actionItem(3, { priority: 78 }),
    ]);
    group.total_count = 5;
    vi.mocked(api.actionItemQueue.list).mockResolvedValue({
      items: [group],
      total: 12,
      matching_count: 21,
    });
    renderWithProviders(<ActionItemsIndexPage />);
    const region = await screen.findByRole('region', { name: 'Epic Release' });
    expect(within(region).getByText('2 of 5 matching')).toBeVisible();
    expect(within(region).getByLabelText('Priority 1')).toBeVisible();
    expect(within(region).getByLabelText('Priority 2')).toBeVisible();
    expect(
      screen.getByText('12 items and Epics · 21 matching Action Items'),
    ).toBeVisible();
    fireEvent.click(within(region).getByRole('button', { name: 'Release' }));
    expect(
      within(region).queryByRole('button', { name: 'Task 2' }),
    ).not.toBeInTheDocument();
    expect(api.actionItemQueue.move).not.toHaveBeenCalled();
  });

  it('moves a filtered child using its full displayed parent cohort and a same-parent anchor', async () => {
    const group = epicGroup(10, [actionItem(2), actionItem(3)]);
    group.total_count = 8;
    vi.mocked(api.actionItemQueue.list).mockResolvedValue({
      items: [group],
      total: 1,
      matching_count: 2,
    });
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items?project=Work&q=Task'],
    });
    fireEvent.click(await findActionButton('Move Task 3 to top'));
    await waitFor(() =>
      expect(api.actionItemQueue.move).toHaveBeenCalledExactlyOnceWith({
        source: { kind: 'item', id: 3, expected_revision: 1 },
        parent: { id: 10, expected_revision: 3, cohort: 'cohort-10' },
        before: { kind: 'item', id: 2, expected_revision: 1 },
      }),
    );
    expect(api.actionItemQueue.list).toHaveBeenCalledTimes(2);
  });

  it('uses same-filter root edge probes and an Epic identity rather than a child anchor', async () => {
    const group = epicGroup();
    vi.mocked(api.actionItemQueue.list).mockImplementation(async (filters) =>
      filters?.limit === 1
        ? queuePage({ items: [actionItem(9)], total: 2 })
        : { items: [group], total: 2, matching_count: 3 },
    );
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items?project=Work&tags=security&q=Task'],
    });
    fireEvent.click(await findActionButton('Move Epic Release to bottom'));
    await waitFor(() =>
      expect(api.actionItemQueue.move).toHaveBeenCalledExactlyOnceWith({
        source: {
          kind: 'epic',
          id: 10,
          expected_revision: 3,
          cohort: 'cohort-10',
        },
        after: { kind: 'item', id: 9, expected_revision: 1 },
      }),
    );
    expect(api.actionItemQueue.list).toHaveBeenCalledWith(
      expect.objectContaining({
        project: 'Work',
        q: 'Task',
        tags: ['security'],
        sort: 'manual_desc',
        limit: 1,
        offset: 0,
      }),
    );
  });

  it('allows completed membership changes to No Epic with the displayed source snapshot', async () => {
    vi.mocked(api.actionItemQueue.list).mockResolvedValue({
      items: [
        epicGroup(10, [actionItem(2, { status: 'completed', revision: 7 })]),
      ],
      total: 1,
      matching_count: 1,
    });
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items?status=all'],
    });
    fireEvent.click(await findActionButton('Move Task 2 to Epic'));
    const picker = await screen.findByRole('combobox', {
      name: 'Move to Epic',
    });
    await waitFor(() => expect(picker).toBeEnabled());
    fireEvent.change(picker, { target: { value: '' } });
    await waitFor(() =>
      expect(api.actionItemQueue.setEpic).toHaveBeenCalledExactlyOnceWith(2, {
        expected_revision: 7,
        expected_parent: { id: 10, expected_revision: 3, cohort: 'cohort-10' },
        destination: null,
      }),
    );
    expect(api.actionItems.update).not.toHaveBeenCalled();
  });

  it('disambiguates duplicate Epic names and cancels the picker without a write', async () => {
    const other = { ...epicGroup().epic, id: 11 };
    vi.mocked(api.actionItemEpics.list).mockResolvedValue({
      items: [epicGroup().epic, other],
    });
    renderWithProviders(<ActionItemsIndexPage />);
    const button = await findActionButton('Move Task 2 to Epic');
    fireEvent.click(button);
    await screen.findByRole('option', { name: 'Release #11' });
    expect(
      screen.getByRole('option', { name: 'Release #10' }),
    ).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Move to Epic' }), {
      key: 'Escape',
    });
    expect(button).toHaveFocus();
    expect(api.actionItemQueue.setEpic).not.toHaveBeenCalled();
  });

  it('preserves an ambiguous create payload and single flight while keeping its form usable', async () => {
    const save = deferred<ActionItemEpic>();
    vi.mocked(api.actionItemEpics.create)
      .mockReturnValueOnce(save.promise)
      .mockRejectedValueOnce(new Error('Uncertain response'));
    renderWithProviders(<ActionItemsIndexPage />);
    await screen.findByRole('button', { name: 'Task 2' });
    fireEvent.click(screen.getByRole('button', { name: 'New Epic' }));
    const input = screen.getByRole('textbox', { name: 'Epic name' });
    expect(input).toBeEnabled();
    expect(
      screen.getByRole('button', { name: 'Reorder Epic Release' }),
    ).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Reorder Task 2' }),
    ).toBeDisabled();
    fireEvent.change(input, { target: { value: 'One group' } });
    const button = screen.getByRole('button', { name: 'Save Epic' });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(api.actionItemEpics.create).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    await act(async () => save.reject(new Error('Uncertain response')));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Uncertain response',
    );
    expect(input).toHaveValue('One group');
    expect(input).toBeEnabled();
    expect(input).toHaveAttribute('readonly');
    fireEvent.change(input, { target: { value: 'Changed after uncertainty' } });
    expect(input).toHaveValue('One group');
    fireEvent.click(button);
    await waitFor(() =>
      expect(api.actionItemEpics.create).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(api.actionItemEpics.create).mock.calls[1]).toEqual(
      vi.mocked(api.actionItemEpics.create).mock.calls[0],
    );
  });

  it('keeps a rejected removal atomic and requires a fresh explicit confirmation after reread', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const first = epicGroup();
    const second = epicGroup();
    second.epic = { ...second.epic, revision: 4, cohort: 'changed-membership' };
    vi.mocked(api.actionItemQueue.list)
      .mockResolvedValueOnce({ items: [first], total: 1, matching_count: 1 })
      .mockResolvedValue({ items: [second], total: 1, matching_count: 1 });
    vi.mocked(api.actionItemEpics.remove).mockRejectedValueOnce(
      new ApiError('Epic changed', 409),
    );
    renderWithProviders(<ActionItemsIndexPage />);
    fireEvent.click(
      await screen.findByRole('button', { name: 'Actions for Epic Release' }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Remove Epic' }));
    await waitFor(() =>
      expect(api.actionItemQueue.list).toHaveBeenCalledTimes(2),
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Epic changed');
    expect(api.actionItemEpics.remove).toHaveBeenCalledExactlyOnceWith(10, {
      expected_revision: 3,
      cohort: 'cohort-10',
    });
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Actions for Epic Release' }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Actions for Epic Release' }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Remove Epic' }));
    await waitFor(() =>
      expect(api.actionItemEpics.remove).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(api.actionItemEpics.remove).mock.calls[1]).toEqual([
      10,
      { expected_revision: 4, cohort: 'changed-membership' },
    ]);
    expect(confirm).toHaveBeenCalledTimes(2);
    confirm.mockRestore();
  });

  it('locates a new Epic explicitly with fresh catalog position and unfiltered Open preferences', async () => {
    const created = {
      ...epicGroup().epic,
      id: 20,
      title: 'Outside this filter',
      position: 23,
    };
    vi.mocked(api.actionItemEpics.create).mockResolvedValue(created);
    const catalog = deferred<{ items: ActionItemEpic[] }>();
    vi.mocked(api.actionItemEpics.list).mockReturnValue(catalog.promise);
    vi.mocked(api.actionItemQueue.list).mockResolvedValue({
      items: [epicGroup()],
      total: 25,
      matching_count: 25,
    });
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items?project=Work&q=Task&tags=security'],
    });
    await screen.findByRole('button', { name: 'Task 2' });
    fireEvent.click(screen.getByRole('button', { name: 'New Epic' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Epic name' }), {
      target: { value: created.title },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Epic' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Show Epic' }));
    expect(
      screen.getByRole('button', { name: 'Reorder Epic Release' }),
    ).toBeDisabled();
    await act(async () => catalog.resolve({ items: [created] }));
    await waitFor(() =>
      expect(api.actionItemQueue.list).toHaveBeenLastCalledWith(
        expect.objectContaining({
          status: 'open',
          sort: 'manual',
          project: undefined,
          q: undefined,
          tags: [],
          limit: 10,
          offset: 20,
        }),
      ),
    );
    expect(screen.getByRole('button', { name: 'Show Epic' })).toBeEnabled();
  });

  it('does not reconcile after an unmounted Epic create completes', async () => {
    const save = deferred<ActionItemEpic>();
    vi.mocked(api.actionItemEpics.create).mockReturnValue(save.promise);
    const view = renderWithProviders(<ActionItemsIndexPage />);
    await screen.findByRole('button', { name: 'Task 2' });
    fireEvent.click(screen.getByRole('button', { name: 'New Epic' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Epic name' }), {
      target: { value: 'Later' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Epic' }));
    view.unmount();
    await act(async () => save.resolve(epicGroup().epic));
    expect(api.actionItemQueue.list).toHaveBeenCalledTimes(1);
  });

  it('unlocks the page when a conflicting membership refresh removes its editing row', async () => {
    vi.mocked(api.actionItemQueue.list)
      .mockResolvedValueOnce({
        items: [epicGroup()],
        total: 1,
        matching_count: 1,
      })
      .mockResolvedValue(queuePage({ items: [actionItem(9)], total: 1 }));
    vi.mocked(api.actionItemQueue.setEpic).mockRejectedValue(
      new ApiError('Source changed', 409),
    );
    renderWithProviders(<ActionItemsIndexPage />);
    fireEvent.click(await findActionButton('Move Task 2 to Epic'));
    const picker = await screen.findByRole('combobox', {
      name: 'Move to Epic',
    });
    await waitFor(() => expect(picker).toBeEnabled());
    fireEvent.change(picker, { target: { value: '' } });
    expect(await screen.findByRole('button', { name: 'Task 9' })).toBeVisible();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'New Epic' })).toBeEnabled(),
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Source changed');
    expect(api.actionItemQueue.setEpic).toHaveBeenCalledTimes(1);
  });

  it('restores the canonical parent after a conflict so the same destination can be chosen again', async () => {
    const first = epicGroup();
    const current = epicGroup();
    current.epic = { ...current.epic, revision: 4, cohort: 'fresh-source' };
    const destination = { ...epicGroup(20).epic, title: 'Next group' };
    vi.mocked(api.actionItemQueue.list)
      .mockResolvedValueOnce({ items: [first], total: 1, matching_count: 1 })
      .mockResolvedValue({ items: [current], total: 1, matching_count: 1 });
    vi.mocked(api.actionItemEpics.list).mockResolvedValue({
      items: [first.epic, destination],
    });
    vi.mocked(api.actionItemQueue.setEpic)
      .mockRejectedValueOnce(new ApiError('Changed source', 409))
      .mockResolvedValue(actionItem(2));
    renderWithProviders(<ActionItemsIndexPage />);
    fireEvent.click(await findActionButton('Move Task 2 to Epic'));
    const picker = await screen.findByRole('combobox', {
      name: 'Move to Epic',
    });
    await waitFor(() => expect(picker).toBeEnabled());
    fireEvent.change(picker, { target: { value: '20' } });
    await waitFor(() =>
      expect(api.actionItemQueue.list).toHaveBeenCalledTimes(2),
    );
    expect(picker).toHaveValue('10');
    expect(screen.getByRole('alert')).toHaveTextContent('Changed source');
    expect(api.actionItemQueue.setEpic).toHaveBeenCalledTimes(1);
    fireEvent.change(picker, { target: { value: '20' } });
    await waitFor(() =>
      expect(api.actionItemQueue.setEpic).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(api.actionItemQueue.setEpic).mock.calls[1]).toEqual([
      2,
      {
        expected_revision: 1,
        expected_parent: {
          id: 10,
          expected_revision: 4,
          cohort: 'fresh-source',
        },
        destination: { id: 20, expected_revision: 3, cohort: 'cohort-20' },
      },
    ]);
  });
});
