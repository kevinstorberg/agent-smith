import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError, type ActionItemEpic } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { EpicsIndexPage } from '../EpicsIndexPage';
import { deferred } from './actionItemFixture';
import { epicGroup } from './actionItemEpicFixture';

vi.mock('../../api', async (original) => {
  const actual = await original<typeof import('../../api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      actionItems: { ...actual.api.actionItems, list: vi.fn() },
      actionItemQueue: { ...actual.api.actionItemQueue, list: vi.fn() },
      actionItemEpics: { list: vi.fn(), rename: vi.fn(), remove: vi.fn() },
    },
  };
});

const epic = (
  id: number,
  fields: Partial<ActionItemEpic> = {},
): ActionItemEpic => ({
  ...epicGroup(id, []).epic,
  title: `Epic ${id}`,
  total_count: 0,
  ...fields,
});
let catalog: ActionItemEpic[];

beforeEach(() => {
  vi.resetAllMocks();
  catalog = [
    epic(10, { title: 'Empty planning' }),
    epic(20, { title: 'Completed delivery', total_count: 4 }),
    epic(30, { title: 'Open delivery', open_count: 2, total_count: 5 }),
  ];
  vi.mocked(api.actionItemEpics.list).mockImplementation(async () => ({
    items: catalog,
  }));
  vi.mocked(api.actionItemEpics.rename).mockImplementation(
    async (id, fields) => {
      const saved = {
        ...catalog.find((entry) => entry.id === id)!,
        title: fields.title,
        revision: fields.expected_revision + 1,
      };
      catalog = catalog.map((entry) => (entry.id === id ? saved : entry));
      return saved;
    },
  );
  vi.mocked(api.actionItemEpics.remove).mockImplementation(async (id) => {
    catalog = catalog.filter((entry) => entry.id !== id);
    return { deleted: true, id };
  });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

it('loads all Epics independently of task filters and searches without another read or write', async () => {
  renderWithProviders(<EpicsIndexPage />, {
    initialEntries: [
      '/action-items/epics?project=Other&status=completed&q=missing&tags=hidden',
    ],
  });
  await screen.findByText('Empty planning');
  expect(screen.getByText('Completed delivery')).toBeVisible();
  expect(screen.getByText('Open delivery')).toBeVisible();
  expect(api.actionItemEpics.list).toHaveBeenCalledExactlyOnceWith();
  expect(api.actionItemQueue.list).not.toHaveBeenCalled();
  expect(api.actionItems.list).not.toHaveBeenCalled();
  for (const column of ['Name', 'Open', 'Total', 'Updated', 'Actions'])
    expect(screen.getByRole('columnheader', { name: column })).toBeVisible();
  fireEvent.change(screen.getByRole('textbox', { name: 'Search Epics' }), {
    target: { value: 'COMPLETED' },
  });
  expect(screen.queryByText('Empty planning')).not.toBeInTheDocument();
  expect(screen.getByText('Completed delivery')).toBeVisible();
  expect(screen.getByText('Showing 1 of 3 Epics')).toBeVisible();
  expect(api.actionItemEpics.list).toHaveBeenCalledTimes(1);
  expect(api.actionItemEpics.rename).not.toHaveBeenCalled();
  expect(api.actionItemEpics.remove).not.toHaveBeenCalled();
});

it('distinguishes duplicate names and confirms keeping children before one revision/cohort-checked delete', async () => {
  catalog = [
    epic(10, { title: 'Delivery', total_count: 4 }),
    epic(20, { title: 'Delivery' }),
  ];
  renderWithProviders(<EpicsIndexPage />);
  fireEvent.click(
    await screen.findByRole('button', { name: 'Delete Epic Delivery #10' }),
  );
  expect(window.confirm).toHaveBeenCalledWith(
    'Delete Epic “Delivery #10”? Its action items will be kept and moved out of the Epic.',
  );
  await waitFor(() =>
    expect(api.actionItemEpics.remove).toHaveBeenCalledExactlyOnceWith(10, {
      expected_revision: 3,
      cohort: 'cohort-10',
    }),
  );
  await waitFor(() =>
    expect(screen.queryByText('Delivery #10')).not.toBeInTheDocument(),
  );
  expect(screen.getByText('Delivery')).toBeVisible();
  expect(api.actionItemEpics.list).toHaveBeenCalledTimes(2);
});

it('cancels deletion without a write or refresh', async () => {
  vi.mocked(window.confirm).mockReturnValue(false);
  renderWithProviders(<EpicsIndexPage />);
  fireEvent.click(
    await screen.findByRole('button', {
      name: 'Delete Epic Completed delivery',
    }),
  );
  expect(api.actionItemEpics.remove).not.toHaveBeenCalled();
  expect(api.actionItemEpics.list).toHaveBeenCalledTimes(1);
});

it('refreshes a stale delete and requires another explicit confirmation with the new full cohort', async () => {
  vi.mocked(api.actionItemEpics.remove).mockImplementationOnce(async () => {
    catalog = catalog.map((entry) =>
      entry.id === 20
        ? {
            ...entry,
            revision: 4,
            cohort: 'current-hidden-completed-cohort',
            total_count: 7,
          }
        : entry,
    );
    throw new ApiError('Epic membership changed. Review it again.', 409);
  });
  renderWithProviders(<EpicsIndexPage />);
  fireEvent.click(
    await screen.findByRole('button', {
      name: 'Delete Epic Completed delivery',
    }),
  );
  await screen.findByRole('alert');
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Delete Epic Completed delivery' }),
    ).toBeEnabled(),
  );
  expect(api.actionItemEpics.remove).toHaveBeenCalledTimes(1);
  expect(api.actionItemEpics.remove).toHaveBeenLastCalledWith(20, {
    expected_revision: 3,
    cohort: 'cohort-20',
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Delete Epic Completed delivery' }),
  );
  await waitFor(() =>
    expect(api.actionItemEpics.remove).toHaveBeenCalledTimes(2),
  );
  expect(api.actionItemEpics.remove).toHaveBeenLastCalledWith(20, {
    expected_revision: 4,
    cohort: 'current-hidden-completed-cohort',
  });
  expect(window.confirm).toHaveBeenCalledTimes(2);
});

it('renames with the displayed revision and restores its own control after canceling', async () => {
  renderWithProviders(<EpicsIndexPage />);
  const trigger = await screen.findByRole('button', {
    name: 'Rename Epic Empty planning',
  });
  trigger.focus();
  fireEvent.click(trigger);
  const name = screen.getByRole('textbox', { name: 'Epic name' });
  expect(name).toHaveFocus();
  fireEvent.change(name, { target: { value: 'Reviewed planning' } });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  await waitFor(() => expect(trigger).toHaveFocus());
  expect(api.actionItemEpics.rename).not.toHaveBeenCalled();
  fireEvent.click(trigger);
  fireEvent.change(screen.getByRole('textbox', { name: 'Epic name' }), {
    target: { value: 'Reviewed planning' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save Epic' }));
  await waitFor(() =>
    expect(api.actionItemEpics.rename).toHaveBeenCalledExactlyOnceWith(10, {
      title: 'Reviewed planning',
      expected_revision: 3,
    }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole('textbox', { name: 'Epic name' }),
    ).not.toBeInTheDocument(),
  );
  expect(screen.getByText('Reviewed planning')).toBeVisible();
});

it('retains the rename draft across a conflict and does not silently replace its revision', async () => {
  vi.mocked(api.actionItemEpics.rename).mockImplementationOnce(async () => {
    catalog = catalog.map((entry) =>
      entry.id === 10
        ? { ...entry, title: 'Current planning', revision: 4 }
        : entry,
    );
    throw new ApiError('Epic changed.', 409);
  });
  renderWithProviders(<EpicsIndexPage />);
  fireEvent.click(
    await screen.findByRole('button', { name: 'Rename Epic Empty planning' }),
  );
  fireEvent.change(screen.getByRole('textbox', { name: 'Epic name' }), {
    target: { value: 'My draft' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save Epic' }));
  await screen.findByText('Current planning');
  expect(screen.getByRole('textbox', { name: 'Epic name' })).toHaveValue(
    'My draft',
  );
  fireEvent.click(screen.getByRole('button', { name: 'Save Epic' }));
  expect(api.actionItemEpics.rename).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('alert')).toHaveTextContent(
    'Cancel editing and review it',
  );
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  fireEvent.click(
    screen.getByRole('button', { name: 'Rename Epic Current planning' }),
  );
  expect(screen.getByRole('textbox', { name: 'Epic name' })).toHaveValue(
    'Current planning',
  );
});

it('keeps controls locked through the write and canonical refresh and prevents repeated deletion', async () => {
  const saving = deferred<{ deleted: boolean; id: number }>();
  const refreshing = deferred<{ items: ActionItemEpic[] }>();
  vi.mocked(api.actionItemEpics.remove).mockReturnValue(saving.promise);
  vi.mocked(api.actionItemEpics.list)
    .mockResolvedValueOnce({ items: catalog })
    .mockReturnValue(refreshing.promise);
  renderWithProviders(<EpicsIndexPage />);
  const trigger = await screen.findByRole('button', {
    name: 'Delete Epic Completed delivery',
  });
  fireEvent.click(trigger);
  fireEvent.click(trigger);
  expect(api.actionItemEpics.remove).toHaveBeenCalledTimes(1);
  expect(trigger).toBeDisabled();
  await act(async () => saving.resolve({ deleted: true, id: 20 }));
  expect(trigger).toBeDisabled();
  await act(async () =>
    refreshing.resolve({ items: catalog.filter((entry) => entry.id !== 20) }),
  );
  expect(
    screen.queryByRole('button', { name: 'Delete Epic Completed delivery' }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Refresh Epics' })).toBeEnabled();
});

it('keeps stale catalog actions disabled after a refresh failure and recovers explicitly', async () => {
  vi.mocked(api.actionItemEpics.list)
    .mockRejectedValueOnce(new Error('Unavailable'))
    .mockResolvedValue({ items: catalog });
  renderWithProviders(<EpicsIndexPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
  await screen.findByText('Empty planning');
  expect(
    screen.getByRole('button', { name: 'Delete Epic Empty planning' }),
  ).toBeEnabled();
  expect(
    within(screen.getByRole('table', { name: 'Epics' })).getAllByRole('row'),
  ).toHaveLength(4);
});
