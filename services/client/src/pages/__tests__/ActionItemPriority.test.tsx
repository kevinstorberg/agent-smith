import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api';
import { renderWithProviders } from '../../test-utils';
import {
  defaultView,
  mergeViewCookie,
  readViewCookie,
} from '../../utils/viewPreferences';
import { ActionItemsIndexPage } from '../ActionItemsIndexPage';
import { actionItem, deferred } from './actionItemFixture';
import { epicGroup, queuePage } from './actionItemEpicFixture';

vi.mock('../../api', async (original) => {
  const actual = await original<typeof import('../../api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      actionItems: { ...actual.api.actionItems, update: vi.fn() },
      actionItemProjects: { list: vi.fn() },
      actionItemQueue: { list: vi.fn(), move: vi.fn(), setEpic: vi.fn() },
      actionItemEpics: { list: vi.fn(), create: vi.fn() },
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
  vi.mocked(api.actionItemEpics.list).mockResolvedValue({ items: [] });
  vi.mocked(api.actionItemQueue.list).mockResolvedValue(
    queuePage({ items: [actionItem(1)], total: 1 }),
  );
});

function priorityAction(name: string) {
  const trigger = screen.getByRole('button', {
    name: 'More actions for Task 1',
  });
  if (trigger.getAttribute('aria-expanded') === 'false')
    fireEvent.click(trigger);
  return screen.getByRole('button', { name });
}

describe('persistent global Priority planning', () => {
  it('makes one minimal revision-checked write and refreshes canonically without changing order', async () => {
    const pending = deferred<ReturnType<typeof actionItem>>();
    let marked = false;
    vi.mocked(api.actionItemQueue.list).mockImplementation(async () =>
      queuePage({
        items: [
          actionItem(1, { is_priority: marked, revision: marked ? 2 : 1 }),
        ],
        total: 1,
      }),
    );
    vi.mocked(api.actionItems.update).mockReturnValueOnce(pending.promise);
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items'],
    });
    await screen.findByRole('button', { name: 'Task 1' });
    const action = priorityAction('Mark Task 1 as Priority');
    fireEvent.click(action);
    fireEvent.click(action);
    expect(api.actionItems.update).toHaveBeenCalledExactlyOnceWith(1, {
      expected_revision: 1,
      is_priority: true,
    });
    expect(
      screen.getByRole('checkbox', { name: 'Priority only' }),
    ).toBeDisabled();
    marked = true;
    await act(async () =>
      pending.resolve(actionItem(1, { is_priority: true, revision: 2 })),
    );
    await waitFor(() =>
      expect(
        screen.getByRole('checkbox', { name: 'Priority only' }),
      ).toBeEnabled(),
    );
    expect(screen.getByText('Priority', { exact: true })).toBeVisible();
    expect(screen.getByLabelText('Order 1')).toHaveTextContent('1');
    expect(priorityAction('Remove Priority from Task 1')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(api.actionItemQueue.move).not.toHaveBeenCalled();
    expect(api.actionItemQueue.setEpic).not.toHaveBeenCalled();
  });

  it('keeps a stale toggle explicit after canonical refresh and never retries automatically', async () => {
    vi.mocked(api.actionItemQueue.list)
      .mockResolvedValueOnce(queuePage({ items: [actionItem(1)], total: 1 }))
      .mockResolvedValue(
        queuePage({ items: [actionItem(1, { revision: 7 })], total: 1 }),
      );
    vi.mocked(api.actionItems.update)
      .mockRejectedValueOnce(new ApiError('Task changed', 409))
      .mockResolvedValue(actionItem(1, { revision: 8, is_priority: true }));
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items'],
    });
    await screen.findByRole('button', { name: 'Task 1' });
    fireEvent.click(priorityAction('Mark Task 1 as Priority'));
    await screen.findByRole('alert');
    await waitFor(() =>
      expect(
        screen.getByRole('checkbox', { name: 'Priority only' }),
      ).toBeEnabled(),
    );
    expect(api.actionItems.update).toHaveBeenCalledTimes(1);
    fireEvent.click(priorityAction('Mark Task 1 as Priority'));
    await waitFor(() =>
      expect(api.actionItems.update).toHaveBeenCalledTimes(2),
    );
    expect(api.actionItems.update).toHaveBeenLastCalledWith(1, {
      expected_revision: 7,
      is_priority: true,
    });
  });

  it('keeps the quick filter visible, resets paging, persists it and clears it explicitly', async () => {
    document.cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      offset: 20,
    });
    vi.mocked(api.actionItemQueue.list).mockResolvedValue(
      queuePage({ items: [actionItem(1)], total: 50 }),
    );
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items'],
    });
    await screen.findByRole('button', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Priority only' }));
    await waitFor(() =>
      expect(api.actionItemQueue.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ priority_only: true, offset: 0 }),
      ),
    );
    expect(
      readViewCookie(document.cookie).find(
        (entry) => entry.key === 'actionItems',
      )?.values.priority_only,
    ).toBe(true);
    expect(screen.getByRole('button', { name: 'More filters' })).toBeVisible();
    expect(
      screen.queryByRole('button', { name: 'Clear filters' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Active filters')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Priority only' }));
    await waitFor(() =>
      expect(api.actionItemQueue.list).toHaveBeenLastCalledWith(
        expect.not.objectContaining({ priority_only: true }),
      ),
    );
    expect(
      screen.getByRole('checkbox', { name: 'Priority only' }),
    ).not.toBeChecked();
  });

  it('counts only advanced filters and clears Priority together with those filters', async () => {
    document.cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      priority_only: true,
      tags: 'security',
    });
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items'],
    });
    await screen.findByRole('button', { name: 'Task 1' });
    expect(
      screen.getByRole('button', { name: 'More filters (1)' }),
    ).toBeVisible();
    expect(screen.getByLabelText('Active filters')).toHaveTextContent(
      'Tags: security',
    );
    expect(screen.getByLabelText('Active filters')).not.toHaveTextContent(
      'Priority only',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() =>
      expect(api.actionItemQueue.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ tags: [], offset: 0 }),
      ),
    );
    expect(api.actionItemQueue.list).toHaveBeenLastCalledWith(
      expect.not.objectContaining({ priority_only: true }),
    );
    expect(
      screen.getByRole('checkbox', { name: 'Priority only' }),
    ).not.toBeChecked();
  });

  it('marks Epic children and clamps the last filtered page after unmarking', async () => {
    document.cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      priority_only: true,
      offset: 10,
    });
    let removed = false;
    vi.mocked(api.actionItemQueue.list).mockImplementation(async (filters) => {
      if (filters?.offset === 10)
        return removed
          ? { items: [], total: 10, matching_count: 10 }
          : {
              items: [epicGroup(10, [actionItem(1, { is_priority: true })])],
              total: 11,
              matching_count: 11,
            };
      return queuePage({
        items: [actionItem(2, { is_priority: true })],
        total: 10,
      });
    });
    vi.mocked(api.actionItems.update).mockImplementation(async () => {
      removed = true;
      return actionItem(1, { is_priority: false, revision: 2 });
    });
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items'],
    });
    await screen.findByRole('button', { name: 'Task 1' });
    fireEvent.click(priorityAction('Remove Priority from Task 1'));
    await screen.findByRole('button', { name: 'Task 2' });
    expect(api.actionItems.update).toHaveBeenCalledExactlyOnceWith(1, {
      expected_revision: 1,
      is_priority: false,
    });
    expect(api.actionItemQueue.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ priority_only: true, offset: 0 }),
    );
    expect(
      screen.getByRole('checkbox', { name: 'Priority only' }),
    ).toBeChecked();
  });
});
