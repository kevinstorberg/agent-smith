import {
  defaultView,
  mergeViewCookie,
  readViewCookie,
} from '../../utils/viewPreferences';
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { StrictMode } from 'react';
import type { DragStart, DropResult } from '@hello-pangea/dnd';
import type { ActionItemRow, Paginated } from '../../api';
import { Link, Route, Routes } from 'react-router';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test-utils';
import { POLL_INTERVAL_MS, actionItemSortOptions } from '../../constants';
import { ActionItemsIndexPage } from '../ActionItemsIndexPage';
import { NotificationBar } from '../../components/NotificationBar';
import { actionItem, deferred } from './actionItemFixture';

const drag = vi.hoisted(() => ({
  start: null as ((start?: DragStart) => void) | null,
  end: null as ((result: DropResult) => Promise<void>) | null,
}));
vi.mock('@hello-pangea/dnd', () => ({
  DragDropContext: ({
    children,
    onBeforeCapture,
    onDragStart,
    onDragEnd,
  }: {
    children: ReactNode;
    onBeforeCapture: () => void;
    onDragStart: (start?: DragStart) => void;
    onDragEnd: (result: DropResult) => Promise<void>;
  }) => {
    drag.start = (start) => {
      onBeforeCapture();
      onDragStart(start);
    };
    drag.end = onDragEnd;
    return <>{children}</>;
  },
  Droppable: ({
    children,
    isDropDisabled,
  }: {
    children: (provided: object) => ReactNode;
    isDropDisabled: boolean;
  }) =>
    children({
      innerRef: () => undefined,
      droppableProps: {
        'data-testid': 'action-items-drop-zone',
        'data-disabled': String(isDropDisabled),
      },
      placeholder: null,
    }),
  Draggable: ({
    children,
    disableInteractiveElementBlocking,
  }: {
    children: (provided: object, snapshot: object) => ReactNode;
    disableInteractiveElementBlocking: boolean;
  }) =>
    children(
      {
        innerRef: () => undefined,
        draggableProps: {
          style: {},
          'data-interactive-drag': String(disableInteractiveElementBlocking),
        },
        dragHandleProps: {},
      },
      { isDragging: false },
    ),
}));
vi.mock('../../api', async (original) => ({
  ...(await original<typeof import('../../api')>()),
  api: {
    actionItemProjects: { list: vi.fn(), create: vi.fn(), remove: vi.fn() },
    actionItems: {
      list: vi.fn(),
      get: vi.fn(),
      update: vi.fn(),
      move: vi.fn(),
      remove: vi.fn(),
    },
  },
}));
import { api, ApiError } from '../../api';

const rows = [actionItem(1), actionItem(2), actionItem(3)];
const drop = (source = 0, destination = 2, id = 1): DropResult => ({
  draggableId: String(id),
  type: 'DEFAULT',
  source: { droppableId: 'action-items', index: source },
  destination: { droppableId: 'action-items', index: destination },
  reason: 'DROP',
  mode: 'FLUID',
  combine: null,
});
const titles = () =>
  within(screen.getByRole('table'))
    .getAllByRole('button')
    .filter((button) => button.hasAttribute('aria-expanded'))
    .map((button) => button.getAttribute('aria-label'));

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.resetAllMocks();
  vi.mocked(api.actionItemProjects.list).mockResolvedValue({
    items: [
      { id: 1, name: 'Work', created_at: '2026-11-01T12:00:00Z' },
      { id: 2, name: 'Paralign', created_at: '2026-11-01T12:00:00Z' },
    ],
    total: 2,
  });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  drag.start = null;
  drag.end = null;
  vi.mocked(api.actionItems.list).mockResolvedValue({ items: rows, total: 3 });
  vi.mocked(api.actionItems.get).mockImplementation(async (id) =>
    actionItem(id),
  );
  vi.mocked(api.actionItems.update).mockResolvedValue(
    actionItem(1, { revision: 2, status: 'completed' }),
  );
  vi.mocked(api.actionItems.move).mockResolvedValue(
    actionItem(1, { revision: 2 }),
  );
  vi.mocked(api.actionItems.remove).mockResolvedValue({ deleted: true, id: 1 });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function renderReady() {
  const rendered = renderWithProviders(<ActionItemsIndexPage />, {
    initialEntries: ['/action-items'],
  });
  await screen.findByRole('button', { name: 'Task 1' });
  return rendered;
}

function liftToProject(project = 'Paralign') {
  act(() => {
    drag.start!({
      draggableId: '1',
      type: 'DEFAULT',
      mode: 'SNAP',
      source: { droppableId: 'action-items', index: 0 },
    });
  });
  fireEvent.keyDown(window, { key: 'ArrowRight' });
  if (project === 'Paralign') fireEvent.keyDown(window, { key: 'ArrowRight' });
}

describe('ActionItemsIndexPage', () => {
  it('keeps project observers idle without a drag and cleans up their exact identities under StrictMode', async () => {
    const added = vi.spyOn(window, 'addEventListener');
    const removed = vi.spyOn(window, 'removeEventListener');
    const rendered = renderWithProviders(
      <StrictMode>
        <ActionItemsIndexPage />
      </StrictMode>,
      { initialEntries: ['/action-items'] },
    );
    await screen.findByRole('button', { name: 'Task 1' });
    const strip = screen.getByRole('tablist', { name: 'Action item projects' });
    const geometry = vi.spyOn(strip, 'getBoundingClientRect');
    fireEvent.mouseMove(window, { clientX: 100, clientY: 20 });
    fireEvent.mouseUp(window, { clientX: 100, clientY: 20 });
    fireEvent.touchEnd(window, {
      changedTouches: [{ clientX: 100, clientY: 20 }],
    });
    expect(geometry).not.toHaveBeenCalled();
    liftToProject('Work');
    expect(screen.getByRole('tab', { name: 'Work' })).toHaveClass(
      'project-drop-target',
    );
    expect(screen.getByRole('tab', { name: 'Paralign' })).not.toHaveClass(
      'project-drop-target',
    );
    const observers = added.mock.calls.filter(([name]) =>
      ['mousemove', 'mouseup', 'touchmove', 'touchend'].includes(name),
    );
    expect(observers.length).toBeGreaterThanOrEqual(4);
    rendered.unmount();
    for (const [name, listener] of observers) {
      expect(removed).toHaveBeenCalledWith(name, listener, true);
    }
    const reads = vi.mocked(api.actionItems.list).mock.calls.length;
    await act(async () => drag.end?.(drop(0, 0)));
    fireEvent.mouseUp(window, { clientX: 100, clientY: 20 });
    expect(api.actionItems.update).not.toHaveBeenCalled();
    expect(api.actionItems.list).toHaveBeenCalledTimes(reads);
  });
  it('assigns the exact captured project with only revision and project in a same-index drop', async () => {
    await renderReady();
    liftToProject();
    await act(async () => drag.end!(drop(0, 0)));
    expect(api.actionItems.update).toHaveBeenCalledExactlyOnceWith(1, {
      expected_revision: 1,
      project: 'Paralign',
    });
    expect(api.actionItems.move).not.toHaveBeenCalled();
    expect(api.actionItems.list).toHaveBeenCalledTimes(2);
  });

  it.each(['cancel', 'same project', 'vertical movement'])(
    'does not assign a project after %s',
    async (reason) => {
      await renderReady();
      liftToProject(reason === 'same project' ? 'Work' : 'Paralign');
      if (reason === 'vertical movement')
        fireEvent.keyDown(window, { key: 'ArrowDown' });
      await act(async () =>
        drag.end!({
          ...drop(0, 0),
          reason: reason === 'cancel' ? 'CANCEL' : 'DROP',
        }),
      );
      expect(api.actionItems.update).not.toHaveBeenCalled();
      expect(api.actionItems.move).not.toHaveBeenCalled();
    },
  );

  it.each(['missing destination', 'same index'])(
    'assigns a named project with %s without invoking the ordering API',
    async (shape) => {
      await renderReady();
      liftToProject();
      await act(async () =>
        drag.end!({
          ...drop(0, 0),
          ...(shape === 'missing destination' ? { destination: null } : {}),
        }),
      );
      expect(api.actionItems.update).toHaveBeenCalledOnce();
      expect(api.actionItems.move).not.toHaveBeenCalled();
    },
  );

  it.each(['removed', 'renamed', 'replaced'])(
    'cancels and refreshes when the captured catalog target is %s',
    async (change) => {
      await renderReady();
      liftToProject();
      const target = screen.getByRole('tab', { name: 'Paralign' });
      if (change === 'removed') target.remove();
      if (change === 'renamed')
        target.setAttribute('data-project-name', 'Other');
      if (change === 'replaced') target.setAttribute('data-project-id', '999');
      await act(async () => drag.end!(drop()));
      expect(api.actionItems.update).not.toHaveBeenCalled();
      expect(api.actionItems.move).not.toHaveBeenCalled();
      expect(api.actionItems.list).toHaveBeenCalledTimes(2);
    },
  );

  it('samples authoritative mouse release before the SDK end callback without relying on hover', async () => {
    await renderReady();
    const strip = screen.getByRole('tablist', { name: 'Action item projects' });
    vi.spyOn(strip, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      right: 400,
      top: 0,
      bottom: 50,
    } as DOMRect);
    for (const [name, left] of [
      ['Work', 100],
      ['Paralign', 200],
    ] as const) {
      vi.spyOn(
        screen.getByRole('tab', { name }),
        'getBoundingClientRect',
      ).mockReturnValue({
        left,
        right: left + 80,
        top: 0,
        bottom: 50,
        width: 80,
        height: 50,
      } as DOMRect);
    }
    act(() => drag.start!());
    fireEvent.mouseMove(window, { clientX: 120, clientY: 25 });
    await act(async () => {
      fireEvent.mouseUp(window, { clientX: 220, clientY: 25 });
      await drag.end!({ ...drop(0, 0), destination: null });
    });
    expect(api.actionItems.update).toHaveBeenCalledExactlyOnceWith(1, {
      expected_revision: 1,
      project: 'Paralign',
    });
  });

  it('does not assign from a stale hover when the pointer releases outside the strip', async () => {
    await renderReady();
    act(() => drag.start!());
    fireEvent.mouseUp(window, { clientX: 999, clientY: 999 });
    await act(async () => drag.end!({ ...drop(0, 0), destination: null }));
    expect(api.actionItems.update).not.toHaveBeenCalled();
  });

  it('uses changedTouches release coordinates instead of the previous touch hover', async () => {
    await renderReady();
    vi.spyOn(
      screen.getByRole('tablist', { name: 'Action item projects' }),
      'getBoundingClientRect',
    ).mockReturnValue({ left: 0, right: 400, top: 0, bottom: 50 } as DOMRect);
    for (const [name, left] of [
      ['Work', 100],
      ['Paralign', 200],
    ] as const) {
      vi.spyOn(
        screen.getByRole('tab', { name }),
        'getBoundingClientRect',
      ).mockReturnValue({
        left,
        right: left + 80,
        top: 0,
        bottom: 50,
        width: 80,
        height: 50,
      } as DOMRect);
    }
    act(() => drag.start!());
    fireEvent.touchMove(window, {
      changedTouches: [{ clientX: 120, clientY: 25 }],
    });
    fireEvent.touchEnd(window, {
      changedTouches: [{ clientX: 220, clientY: 25 }],
    });
    await act(async () => drag.end!({ ...drop(0, 0), destination: null }));
    expect(api.actionItems.update).toHaveBeenCalledExactlyOnceWith(1, {
      expected_revision: 1,
      project: 'Paralign',
    });
  });

  it('serializes assignment and keeps controls frozen through the canonical read', async () => {
    const saving = deferred<ReturnType<typeof actionItem>>();
    const reading = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.update).mockReturnValueOnce(saving.promise);
    await renderReady();
    vi.mocked(api.actionItems.list).mockReturnValueOnce(reading.promise);
    liftToProject();
    let ended!: Promise<void>;
    await act(async () => {
      ended = drag.end!(drop(0, 0));
      await Promise.resolve();
    });
    expect(screen.getByLabelText('Search action items')).toBeDisabled();
    await act(async () => drag.end!(drop(0, 0)));
    expect(api.actionItems.update).toHaveBeenCalledOnce();
    await act(async () => {
      saving.resolve(actionItem(1, { project: 'Paralign', revision: 2 }));
    });
    expect(screen.getByLabelText('Search action items')).toBeDisabled();
    await act(async () => {
      reading.resolve({ items: rows, total: 3 });
      await ended;
    });
    expect(screen.getByLabelText('Search action items')).toBeEnabled();
  });

  it.each([
    new ApiError('Source changed', 409),
    new Error('Network unavailable'),
  ])(
    'reports assignment failure without optimistic field changes or automatic retry: %s',
    async (failure) => {
      vi.mocked(api.actionItems.update).mockRejectedValueOnce(failure);
      renderWithProviders(
        <>
          <ActionItemsIndexPage />
          <NotificationBar />
        </>,
        { initialEntries: ['/action-items'] },
      );
      await screen.findByRole('button', { name: 'Task 1' });
      liftToProject();
      await act(async () => drag.end!(drop(0, 0)));
      expect(api.actionItems.update).toHaveBeenCalledOnce();
      expect(api.actionItems.move).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent(failure.message);
      expect(titles()).toEqual(['Task 1', 'Task 2', 'Task 3']);
      expect(screen.getByLabelText('Search action items')).toBeEnabled();
    },
  );

  it.each(
    (['open', 'completed', 'all'] as const).flatMap((status) =>
      actionItemSortOptions(status).map(({ value: sort }) => ({
        status,
        sort,
      })),
    ),
  )(
    'supports project assignment under $status / $sort while preserving reorder restrictions',
    async ({ status, sort }) => {
      renderWithProviders(<ActionItemsIndexPage />, {
        initialEntries: [`/action-items?status=${status}&sort=${sort}`],
      });
      await screen.findByRole('button', { name: 'Task 1' });
      expect(
        screen.getByRole('button', {
          name:
            status === 'open' && sort === 'manual'
              ? 'Reorder Task 1'
              : 'Move Task 1 to project',
        }),
      ).toBeEnabled();
      liftToProject();
      await act(async () => drag.end!({ ...drop(0, 0), destination: null }));
      expect(api.actionItems.update).toHaveBeenCalledExactlyOnceWith(1, {
        expected_revision: 1,
        project: 'Paralign',
      });
      expect(api.actionItems.move).not.toHaveBeenCalled();
    },
  );
  it('refreshes the saved action item page at 15 seconds without writing', async () => {
    vi.useFakeTimers();
    document.cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      q: 'Task',
      project: 'Work',
      limit: 25,
      offset: 50,
    });
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: rows,
      total: 100,
    });
    await act(async () => {
      renderWithProviders(<ActionItemsIndexPage />, {
        initialEntries: ['/action-items'],
      });
    });
    const read = vi.mocked(api.actionItems.list);
    const params = read.mock.calls.at(-1)![0];
    expect(params).toMatchObject({
      q: 'Task',
      project: 'Work',
      limit: 25,
      offset: 50,
    });
    read.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(14_999);
    });
    expect(read).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(read).toHaveBeenCalledExactlyOnceWith(params);
    expect(api.actionItems.update).not.toHaveBeenCalled();
    expect(api.actionItems.move).not.toHaveBeenCalled();
    expect(api.actionItems.remove).not.toHaveBeenCalled();
  });
  it('restores filtered manual ordering and preserves saved criteria during ordinary sort changes', async () => {
    document.cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      q: 'Task',
      project: 'Work',
      tags: 'team, urgent',
      limit: 25,
      offset: 50,
    });
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: rows,
      total: 100,
    });
    await renderReady();
    expect(api.actionItems.list).toHaveBeenCalledTimes(1);
    expect(api.actionItems.list).toHaveBeenCalledWith({
      status: 'open',
      sort: 'manual',
      q: 'Task',
      project: 'Work',
      tags: ['team', 'urgent'],
      limit: 25,
      offset: 50,
    });
    expect(
      screen.getByRole('button', { name: 'Reorder Task 1' }),
    ).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Title' }));
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith({
        status: 'open',
        sort: 'title',
        q: 'Task',
        project: 'Work',
        tags: ['team', 'urgent'],
        limit: 25,
        offset: 0,
      }),
    );
    expect(readViewCookie(document.cookie)).toEqual([
      {
        key: 'actionItems',
        values: {
          q: 'Task',
          project: 'Work',
          tags: 'team, urgent',
          sort: 'title',
          limit: 25,
        },
      },
    ]);
  });

  it('honors explicit clears and normalizes an incompatible restored status-sort before fetching', async () => {
    document.cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      q: 'old',
      status: 'completed',
      sort: 'completed',
      limit: 25,
      offset: 50,
    });
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items?q=&status=all&sort=manual'],
    });
    await screen.findByRole('button', { name: 'Task 1' });
    expect(api.actionItems.list).toHaveBeenCalledTimes(1);
    expect(api.actionItems.list).toHaveBeenCalledWith(
      expect.objectContaining({
        q: undefined,
        status: 'all',
        sort: 'newest',
        limit: 25,
        offset: 0,
      }),
    );
    expect(
      screen.queryByRole('columnheader', { name: /Title/ }),
    ).not.toHaveAttribute('aria-sort');
  });

  it('keeps title disclosures separate from right-side completion and Edit controls', async () => {
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.update).mockReturnValueOnce(saving.promise);
    await renderReady();
    expect(
      screen.getByRole('link', { name: 'New action item' }),
    ).toHaveAttribute('href', '/action-items/new');
    expect(screen.getByRole('button', { name: 'Task 1' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(
      screen.queryByRole('link', { name: 'Task 1' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Reorder Task 1' }).closest('tr'),
    ).toHaveAttribute('data-interactive-drag', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Complete Task 1' }));
    expect(api.actionItems.update).toHaveBeenCalledWith(1, {
      expected_revision: 1,
      status: 'completed',
    });
    expect(
      screen.getByRole('button', { name: 'Complete Task 2' }),
    ).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Complete Task 1' }),
    ).toHaveTextContent('Complete');
    await act(async () => {
      saving.resolve(actionItem(1, { revision: 2, status: 'completed' }));
    });
  });

  it('uses tab-specific sorts and reopens completed items through explicit state', async () => {
    await renderReady();
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: [actionItem(1, { status: 'completed', revision: 4 })],
      total: 1,
    });
    fireEvent.click(screen.getByRole('tab', { name: 'Completed' }));
    await screen.findByRole('button', { name: 'Reopen Task 1' });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'completed', sort: 'completed' }),
    );
    expect(
      screen.queryByRole('option', { name: 'Manual order' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reopen Task 1' }));
    await waitFor(() =>
      expect(api.actionItems.update).toHaveBeenCalledWith(1, {
        expected_revision: 4,
        status: 'open',
      }),
    );
    fireEvent.click(screen.getByRole('tab', { name: 'All' }));
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: 'all', sort: 'newest' }),
      ),
    );
  });

  it('debounces typing once, keeps search focused, and resets paging before the new query', async () => {
    vi.useFakeTimers();
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: rows,
      total: 25,
    });
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items'],
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: 'Task 1' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 10 }),
    );
    vi.mocked(api.actionItems.list).mockClear();
    const search = screen.getByLabelText('Search action items');
    search.focus();
    fireEvent.change(search, { target: { value: 'Ro' } });
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    fireEvent.change(search, { target: { value: 'Roadmap' } });
    await act(async () => {
      vi.advanceTimersByTime(299);
    });
    expect(api.actionItems.list).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(api.actionItems.list).toHaveBeenCalledTimes(1);
    expect(api.actionItems.list).toHaveBeenCalledWith(
      expect.objectContaining({ q: 'Roadmap', offset: 0 }),
    );
    expect(search).toHaveFocus();
    expect(screen.getByTestId('action-items-drop-zone')).toHaveAttribute(
      'data-disabled',
      'false',
    );
  });

  it('sends combined project/tags filters to the server and applies select changes immediately', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    fireEvent.click(screen.getByRole('tab', { name: 'Paralign' }));
    fireEvent.change(screen.getByLabelText('Tags'), {
      target: { value: 'product, security' },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(
      expect.objectContaining({
        project: 'Paralign',
        tags: ['product', 'security'],
        offset: 0,
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Title' }));
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({
          sort: 'title',
          project: 'Paralign',
          tags: ['product', 'security'],
        }),
      ),
    );
  });

  it('ignores late search responses after newer criteria return', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    const stale = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list)
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce({
        items: [actionItem(4, { title: 'Current result' })],
        total: 1,
      });
    fireEvent.change(screen.getByLabelText('Search action items'), {
      target: { value: 'old' },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    fireEvent.change(screen.getByLabelText('Search action items'), {
      target: { value: 'new' },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    await screen.findByRole('button', { name: 'Current result' });
    await act(async () => {
      stale.resolve({
        items: [actionItem(5, { title: 'Stale result' })],
        total: 1,
      });
    });
    expect(screen.queryByText('Stale result')).not.toBeInTheDocument();
    expect(screen.getByText('Current result')).toBeVisible();
  });

  it('clamps an emptied last page after completion', async () => {
    vi.mocked(api.actionItems.list)
      .mockResolvedValueOnce({ items: rows, total: 11 })
      .mockResolvedValueOnce({ items: [actionItem(11)], total: 11 })
      .mockResolvedValueOnce({ items: [], total: 10 })
      .mockResolvedValueOnce({ items: rows, total: 10 });
    await renderReady();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByRole('button', { name: 'Complete Task 11' });
    fireEvent.click(screen.getByRole('button', { name: 'Complete Task 11' }));
    await screen.findByRole('button', { name: 'Task 1' });
    expect(api.actionItems.update).toHaveBeenCalledWith(11, {
      expected_revision: 1,
      status: 'completed',
    });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0 }),
    );
  });

  it('refreshes the current filtered page after a pending status write rather than its captured old offset', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.update).mockReturnValueOnce(saving.promise);
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: rows,
      total: 25,
    });
    await renderReady();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 10 }),
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Complete Task 1' }));
    fireEvent.change(screen.getByLabelText('Search action items'), {
      target: { value: 'Current scope' },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 0, q: 'Current scope' }),
      ),
    );
    vi.mocked(api.actionItems.list).mockClear();
    await act(async () => {
      saving.resolve(actionItem(1, { status: 'completed' }));
    });
    expect(api.actionItems.list).toHaveBeenCalledTimes(1);
    expect(api.actionItems.list).toHaveBeenCalledWith(
      expect.objectContaining({ offset: 0, q: 'Current scope' }),
    );
  });

  it('does not refetch after a pending write finishes on an unmounted page', async () => {
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.update).mockReturnValueOnce(saving.promise);
    const rendered = await renderReady();
    fireEvent.click(screen.getByRole('button', { name: 'Complete Task 1' }));
    rendered.unmount();
    vi.mocked(api.actionItems.list).mockClear();
    await act(async () => {
      saving.resolve(actionItem(1, { status: 'completed' }));
    });
    expect(api.actionItems.list).not.toHaveBeenCalled();
  });

  it('sends page-end relative intent after the last visible neighbor and freezes controls through its save', async () => {
    const page = Array.from({ length: 10 }, (_, index) =>
      actionItem(index + 11),
    );
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.move).mockReturnValueOnce(saving.promise);
    vi.mocked(api.actionItems.list)
      .mockResolvedValueOnce({ items: rows, total: 25 })
      .mockResolvedValue({ items: page, total: 25 });
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items'],
    });
    await screen.findByRole('button', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByRole('button', { name: 'Task 11' });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 10 }),
    );
    act(() => {
      drag.start!();
    });
    let ended!: Promise<void>;
    await act(async () => {
      ended = drag.end!(drop(0, 9, 11));
      await Promise.resolve();
    });
    expect(api.actionItems.move).toHaveBeenCalledWith(11, {
      expected_revision: 1,
      after_id: 20,
    });
    expect(titles().at(-1)).toBe('Task 11');
    expect(screen.getAllByLabelText('Priority updating')).toHaveLength(10);
    expect(screen.getByLabelText('Search action items')).toBeDisabled();
    for (const tab of within(
      screen.getByRole('tablist', { name: 'Action item projects' }),
    ).getAllByRole('tab'))
      expect(tab).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByLabelText('Tags')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Title' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Complete Task 12' }),
    ).toBeDisabled();
    await act(async () => {
      saving.resolve(actionItem(11, { revision: 2 }));
      await ended;
    });
  });

  it('reorders a searched and filtered subset using visible anchors without inventing global priorities', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    const subset = [actionItem(1), actionItem(3), actionItem(5)];
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: subset,
      total: 3,
    });
    fireEvent.change(screen.getByLabelText('Search action items'), {
      target: { value: 'Task' },
    });
    fireEvent.click(screen.getByRole('tab', { name: 'Work' }));
    fireEvent.change(screen.getByLabelText('Tags'), {
      target: { value: 'security' },
    });
    expect(
      screen.getByRole('button', { name: 'Reorder Task 1' }),
    ).toBeDisabled();
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    await screen.findByRole('button', { name: 'Task 5' });
    expect(
      screen.getByRole('button', { name: 'Reorder Task 1' }),
    ).toBeEnabled();
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.move).mockReturnValueOnce(saving.promise);
    act(() => {
      drag.start!();
    });
    let ended!: Promise<void>;
    await act(async () => {
      ended = drag.end!(drop(0, 2, 1));
      await Promise.resolve();
    });
    expect(api.actionItems.move).toHaveBeenCalledWith(1, {
      expected_revision: 1,
      after_id: 5,
    });
    expect(titles()).toEqual(['Task 3', 'Task 5', 'Task 1']);
    expect(screen.getAllByLabelText('Priority updating')).toHaveLength(3);
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: [
        actionItem(3, { priority: 2 }),
        actionItem(5, { priority: 4 }),
        actionItem(1, { revision: 2, priority: 5 }),
      ],
      total: 3,
    });
    await act(async () => {
      saving.resolve(actionItem(1, { revision: 2, priority: 5 }));
      await ended;
    });
    expect(
      [
        ...screen.getByRole('table').querySelectorAll('.action-item-priority'),
      ].map((cell) => cell.textContent),
    ).toEqual(['2', '4', '5']);
  });

  it('moves upward before the next visible neighbor instead of replacing the whole queue', async () => {
    await renderReady();
    act(() => {
      drag.start!();
    });
    await act(async () => {
      await drag.end!(drop(2, 0, 3));
    });
    expect(api.actionItems.move).toHaveBeenCalledWith(3, {
      expected_revision: 1,
      before_id: 1,
    });
  });

  it('retains the same disabled handles throughout a move and its delayed reconciliation', async () => {
    const saving = deferred<ReturnType<typeof actionItem>>();
    const reread = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.move).mockReturnValueOnce(saving.promise);
    await renderReady();
    const table = screen.getByRole('table');
    const handles = screen.getAllByRole('button', { name: /^Reorder / });
    handles[0].focus();
    vi.mocked(api.actionItems.list).mockReturnValueOnce(reread.promise);
    act(() => drag.start!());
    let ended!: Promise<void>;
    await act(async () => {
      ended = drag.end!(drop());
      await Promise.resolve();
    });
    expect(screen.getByRole('table')).toBe(table);
    expect(screen.getAllByRole('button', { name: /^Reorder / })).toHaveLength(
      3,
    );
    for (const handle of handles) {
      expect(handle).toBeInTheDocument();
      expect(handle).toBeDisabled();
    }
    handles[0].blur();
    expect(screen.getByRole('status')).toHaveTextContent('Saving order…');
    expect(screen.getByRole('status')).toHaveClass('visually-hidden');
    await act(async () => {
      saving.resolve(actionItem(1, { revision: 2 }));
    });
    expect(screen.getByRole('table')).toBe(table);
    for (const handle of handles) expect(handle).toBeDisabled();
    await act(async () => {
      reread.resolve({
        items: [rows[1], rows[2], actionItem(1, { revision: 2 })],
        total: 3,
      });
      await ended;
    });
    expect(screen.getByRole('table')).toBe(table);
    for (const handle of handles) expect(handle).toBeEnabled();
    expect(handles[0]).toHaveFocus();
  });

  it('does not steal focus when the user moves away during reconciliation', async () => {
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.move).mockReturnValueOnce(saving.promise);
    await renderReady();
    screen.getByRole('button', { name: 'Reorder Task 1' }).focus();
    act(() => drag.start!());
    let ended!: Promise<void>;
    await act(async () => {
      ended = drag.end!(drop());
      await Promise.resolve();
    });
    const create = screen.getByRole('link', { name: 'New action item' });
    create.focus();
    await act(async () => {
      saving.resolve(actionItem(1, { revision: 2 }));
      await ended;
    });
    expect(create).toHaveFocus();
  });

  it('retains populated rows after a failed move reread and blocks stale completion until Retry succeeds', async () => {
    await renderReady();
    const table = screen.getByRole('table');
    vi.mocked(api.actionItems.list).mockRejectedValueOnce(
      new Error('Synthetic read failure'),
    );
    act(() => drag.start!());
    await act(async () => {
      await drag.end!(drop());
    });
    expect(screen.getByRole('table')).toBe(table);
    expect(titles()).toEqual(['Task 1', 'Task 2', 'Task 3']);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'The current list is kept.',
    );
    expect(screen.getAllByRole('button', { name: /^Reorder / })).toHaveLength(
      3,
    );
    expect(
      screen.getByRole('button', { name: 'Complete Task 1' }),
    ).toBeDisabled();
    expect(api.actionItems.move).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Complete Task 1' }),
      ).toBeEnabled(),
    );
    expect(screen.getByRole('table')).toBe(table);
    expect(api.actionItems.move).toHaveBeenCalledTimes(1);
    expect(api.actionItems.update).not.toHaveBeenCalled();
  });

  it('shows actual queue priorities in filtered title order and completed rows', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: [actionItem(24), actionItem(13), actionItem(3)],
      total: 3,
    });
    fireEvent.click(screen.getByRole('tab', { name: 'Work' }));
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Title' }));
    await screen.findByRole('button', { name: 'Task 24' });
    expect(
      within(screen.getByRole('table'))
        .getAllByRole('columnheader')
        .map((header) => header.textContent?.replace(/[▲▼↕]/g, '')),
    ).toEqual(['Priority', 'Title', 'Project/Tags', 'Due date', 'Actions']);
    expect(
      [
        ...screen.getByRole('table').querySelectorAll('.action-item-priority'),
      ].map((cell) => cell.textContent),
    ).toEqual(['24', '13', '3']);
    expect(
      screen.queryByRole('button', { name: /Reorder/ }),
    ).not.toBeInTheDocument();
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: [actionItem(24, { status: 'completed' })],
      total: 1,
    });
    fireEvent.click(screen.getByRole('tab', { name: 'Completed' }));
    await screen.findByRole('button', { name: 'Reopen Task 24' });
    expect(screen.getByLabelText('No open queue priority')).toHaveTextContent(
      '—',
    );
    const actions = screen
      .getByRole('button', { name: 'Reopen Task 24' })
      .closest('td')!;
    expect(
      within(actions)
        .getAllByRole('button')
        .map((button) => button.textContent),
    ).toEqual(['Reopen', 'Edit', 'Delete']);
  });

  it('lazily discloses descriptions with native keyboard buttons and one open row', async () => {
    const user = userEvent.setup();
    vi.mocked(api.actionItems.get).mockImplementation(async (id) =>
      actionItem(id, { description: id === 1 ? '**Next steps**' : '' }),
    );
    await renderReady();
    expect(api.actionItems.get).not.toHaveBeenCalled();
    const title = screen.getByRole('button', { name: 'Task 1' });
    title.focus();
    await user.keyboard('{Enter}');
    expect(
      await screen.findByRole('region', { name: 'Task 1' }),
    ).toHaveTextContent('Next steps');
    expect(api.actionItems.get).toHaveBeenCalledWith(1);
    expect(title).toHaveAttribute('aria-expanded', 'true');
    expect(title).toHaveAttribute('aria-controls', 'action-description-1');
    expect(
      screen.getByRole('region', { name: 'Task 1' }).closest('td'),
    ).toHaveAttribute('colspan', '5');
    await user.keyboard(' ');
    expect(
      screen.queryByRole('region', { name: /^Task \d+$/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Task 2' }));
    expect(
      await screen.findByRole('region', { name: 'Task 2' }),
    ).toHaveTextContent('No description added.');
    fireEvent.click(title);
    await screen.findByRole('region', { name: 'Task 1' });
    expect(
      screen.queryByRole('region', { name: 'Task 2' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Complete Task 3' }));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Complete Task 3' }),
      ).toBeEnabled(),
    );
    expect(title).toHaveAttribute('aria-expanded', 'true');
  });

  it('retries a failed description read and ignores late responses after collapse', async () => {
    vi.mocked(api.actionItems.get).mockRejectedValueOnce(
      new Error('Private failure'),
    );
    await renderReady();
    fireEvent.click(screen.getByRole('button', { name: 'Task 1' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load this description.',
    );
    expect(screen.queryByText('Private failure')).not.toBeInTheDocument();
    const loading = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.get).mockReturnValueOnce(loading.promise);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    fireEvent.click(screen.getByRole('button', { name: 'Task 1' }));
    await act(async () => {
      loading.resolve(actionItem(1, { description: 'Stale description' }));
    });
    expect(screen.queryByText('Stale description')).not.toBeInTheDocument();
  });

  it('closes descriptions before drag capture and when paging or filters change', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: rows,
      total: 25,
    });
    await renderReady();
    fireEvent.click(screen.getByRole('button', { name: 'Task 1' }));
    await screen.findByRole('region', { name: 'Task 1' });
    act(() => drag.start!());
    expect(
      screen.queryByRole('region', { name: /^Task \d+$/ }),
    ).not.toBeInTheDocument();
    await act(async () => drag.end!({ ...drop(), destination: null }));
    fireEvent.click(screen.getByRole('button', { name: 'Task 1' }));
    await screen.findByRole('region', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(
        screen.queryByRole('region', { name: /^Task \d+$/ }),
      ).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Task 1' }));
    await screen.findByRole('region', { name: 'Task 1' });
    fireEvent.change(screen.getByLabelText('Search action items'), {
      target: { value: 'new' },
    });
    expect(
      screen.queryByRole('region', { name: /^Task \d+$/ }),
    ).not.toBeInTheDocument();
  });

  it('opens Edit directly without reading a description or toggling its disclosure', async () => {
    renderWithProviders(
      <Routes>
        <Route path="/action-items" element={<ActionItemsIndexPage />} />
        <Route path="/action-items/:id" element={<p>Direct editor</p>} />
      </Routes>,
      { initialEntries: ['/action-items'] },
    );
    await screen.findByRole('button', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit Task 1' }));
    expect(await screen.findByText('Direct editor')).toBeVisible();
    expect(api.actionItems.get).not.toHaveBeenCalled();
  });

  it('rejects a drag when only the queue positions changed during an in-flight poll', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    const polling = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list).mockReturnValueOnce(polling.promise);
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    act(() => drag.start!());
    await act(async () => {
      polling.resolve({
        items: rows.map((item) => ({ ...item, priority: item.priority! + 1 })),
        total: 4,
      });
    });
    await act(async () => drag.end!(drop()));
    expect(api.actionItems.move).not.toHaveBeenCalled();
  });

  it('rolls an optimistic reorder back and reloads persisted order after a conflict', async () => {
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.move).mockReturnValueOnce(saving.promise);
    await renderReady();
    act(() => {
      drag.start!();
    });
    let ended!: Promise<void>;
    await act(async () => {
      ended = drag.end!(drop());
      await Promise.resolve();
    });
    expect(titles()).toEqual(['Task 2', 'Task 3', 'Task 1']);
    await act(async () => {
      saving.reject(new ApiError('Source changed', 409));
      await ended;
    });
    expect(titles()).toEqual(['Task 1', 'Task 2', 'Task 3']);
    expect(
      screen.getByRole('button', { name: 'Complete Task 1' }),
    ).toBeEnabled();
    expect(api.actionItems.list).toHaveBeenCalledTimes(2);
  });

  it('blocks captured drag callbacks while filters are pending', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    const oldStart = drag.start!;
    const oldEnd = drag.end!;
    fireEvent.change(screen.getByLabelText('Search action items'), {
      target: { value: 'filtered' },
    });
    act(() => {
      oldStart();
    });
    await act(async () => {
      await oldEnd(drop());
    });
    expect(api.actionItems.move).not.toHaveBeenCalled();
    expect(
      screen.getByRole('button', { name: 'Reorder Task 1' }),
    ).toBeDisabled();
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(
      screen.getByRole('button', { name: 'Reorder Task 1' }),
    ).toBeEnabled();
  });

  it('keeps displayed rows frozen and cancels a drag if an already-started read changes membership', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    const polling = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list).mockReturnValueOnce(polling.promise);
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    act(() => {
      drag.start!();
    });
    await act(async () => {
      polling.resolve({ items: [rows[0], rows[2]], total: 2 });
    });
    expect(titles()).toEqual(['Task 1', 'Task 2', 'Task 3']);
    await act(async () => {
      await drag.end!(drop());
    });
    expect(api.actionItems.move).not.toHaveBeenCalled();
  });

  it('pauses polling during a drag and ignores canceled or unchanged drops', async () => {
    vi.useFakeTimers();
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items'],
    });
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      drag.start!();
    });
    vi.mocked(api.actionItems.list).mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
    });
    expect(api.actionItems.list).not.toHaveBeenCalled();
    await act(async () => {
      await drag.end!({ ...drop(), destination: null, reason: 'CANCEL' });
    });
    act(() => {
      drag.start!();
    });
    await act(async () => {
      await drag.end!(drop(0, 0));
    });
    expect(api.actionItems.move).not.toHaveBeenCalled();
  });

  it('keeps labeled filters available through loading and retryable read failures', async () => {
    vi.mocked(api.actionItems.list).mockRejectedValueOnce(
      new Error('Private diagnostic'),
    );
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items'],
    });
    expect(screen.getByLabelText('Search action items')).toBeVisible();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load action items.',
    );
    expect(screen.queryByText('Private diagnostic')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByRole('button', { name: 'Task 1' });
  });
});

describe('Action Items list deletion', () => {
  async function ready() {
    const rendered = renderWithProviders(
      <>
        <NotificationBar />
        <ActionItemsIndexPage />
      </>,
      { initialEntries: ['/action-items'] },
    );
    await screen.findByRole('button', { name: 'Task 1' });
    return rendered;
  }

  it('confirms the displayed title and leaves cancellation without writes or refreshes', async () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    await ready();
    vi.mocked(api.actionItems.list).mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Delete Task 1' }));
    expect(window.confirm).toHaveBeenCalledWith('Delete action item “Task 1”?');
    expect(api.actionItems.remove).not.toHaveBeenCalled();
    expect(api.actionItems.list).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Task 1' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(api.actionItems.get).not.toHaveBeenCalled();
  });

  it('sends the displayed revision once and holds all row actions through reconciliation', async () => {
    const saving = deferred<{ deleted: boolean; id: number }>();
    const refresh = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list)
      .mockResolvedValueOnce({
        items: [actionItem(1, { revision: 7 }), ...rows.slice(1)],
        total: 3,
      })
      .mockReturnValueOnce(refresh.promise);
    vi.mocked(api.actionItems.remove).mockReturnValueOnce(saving.promise);
    await ready();
    const button = screen.getByRole('button', { name: 'Delete Task 1' });
    act(() => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    expect(api.actionItems.remove).toHaveBeenCalledTimes(1);
    expect(api.actionItems.remove).toHaveBeenCalledWith(1, 7);
    expect(
      screen.getByRole('button', { name: 'Delete Task 2' }),
    ).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Complete Task 2' }),
    ).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Edit Task 2' })).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Reorder Task 2' }),
    ).toBeDisabled();
    await act(async () => saving.resolve({ deleted: true, id: 1 }));
    expect(
      screen.getByRole('button', { name: 'Delete Task 2' }),
    ).toBeDisabled();
    await act(async () => refresh.resolve({ items: rows.slice(1), total: 2 }));
    expect(
      screen.queryByRole('button', { name: 'Task 1' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete Task 2' })).toBeEnabled();
  });

  it('retains the row and requires a new confirmation and displayed revision after a409', async () => {
    vi.mocked(api.actionItems.remove).mockRejectedValueOnce(
      new ApiError('Action item changed', 409),
    );
    vi.mocked(api.actionItems.list)
      .mockResolvedValueOnce({ items: rows, total: 3 })
      .mockResolvedValue({
        items: [actionItem(1, { revision: 9 }), ...rows.slice(1)],
        total: 3,
      });
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Delete Task 1' }));
    await screen.findByRole('alert');
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Delete Task 1' }),
      ).toBeEnabled(),
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Action item changed');
    expect(api.actionItems.remove).toHaveBeenCalledTimes(1);
    expect(api.actionItems.remove).toHaveBeenLastCalledWith(1, 1);
    expect(api.actionItems.get).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete Task 1' }));
    await waitFor(() =>
      expect(api.actionItems.remove).toHaveBeenLastCalledWith(1, 9),
    );
    expect(window.confirm).toHaveBeenCalledTimes(2);
  });

  it('reports ordinary failure, retains the row and unlocks a fresh explicit attempt', async () => {
    vi.mocked(api.actionItems.remove).mockRejectedValueOnce(
      new Error('Could not delete synthetic item'),
    );
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Delete Task 1' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not delete synthetic item',
    );
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Delete Task 1' }),
      ).toBeEnabled(),
    );
    expect(screen.getByRole('button', { name: 'Task 1' })).toBeVisible();
    expect(api.actionItems.remove).toHaveBeenCalledTimes(1);
  });

  it('clamps a last page emptied by deletion and refreshes the preceding page', async () => {
    vi.mocked(api.actionItems.list)
      .mockResolvedValueOnce({ items: rows, total: 11 })
      .mockResolvedValueOnce({ items: [actionItem(11)], total: 11 })
      .mockResolvedValueOnce({ items: [], total: 10 })
      .mockResolvedValue({ items: rows, total: 10 });
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete Task 11' }),
    );
    await screen.findByRole('button', { name: 'Task 1' });
    expect(api.actionItems.remove).toHaveBeenCalledWith(11, 1);
    expect(api.actionItems.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0 }),
    );
    expect(
      screen.queryByRole('button', { name: 'Delete Task 11' }),
    ).not.toBeInTheDocument();
  });

  it('reconciles the latest filter and offset when a captured delete finishes', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const saving = deferred<{ deleted: boolean; id: number }>();
    vi.mocked(api.actionItems.remove).mockReturnValueOnce(saving.promise);
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: rows,
      total: 25,
    });
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 10 }),
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Delete Task 1' }));
    fireEvent.change(screen.getByLabelText('Search action items'), {
      target: { value: 'Current filter' },
    });
    await act(async () => vi.advanceTimersByTime(300));
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: 'Current filter', offset: 0 }),
      ),
    );
    vi.mocked(api.actionItems.list).mockClear();
    await act(async () => saving.resolve({ deleted: true, id: 1 }));
    expect(api.actionItems.remove).toHaveBeenCalledWith(1, 1);
    expect(api.actionItems.list).toHaveBeenCalledTimes(1);
    expect(api.actionItems.list).toHaveBeenCalledWith(
      expect.objectContaining({ q: 'Current filter', offset: 0 }),
    );
  });

  it.each(['resolve', 'reject'] as const)(
    'does not refresh or notify after an unmounted delete %s',
    async (outcome) => {
      const saving = deferred<{ deleted: boolean; id: number }>();
      vi.mocked(api.actionItems.remove).mockReturnValueOnce(saving.promise);
      const rendered = await ready();
      fireEvent.click(screen.getByRole('button', { name: 'Delete Task 1' }));
      expect(api.actionItems.remove).toHaveBeenCalledWith(1, 1);
      rendered.rerender(<NotificationBar />);
      vi.mocked(api.actionItems.list).mockClear();
      await act(async () => {
        if (outcome === 'resolve') saving.resolve({ deleted: true, id: 1 });
        else saving.reject(new Error('Late failure'));
      });
      expect(api.actionItems.list).not.toHaveBeenCalled();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    },
  );

  it('blocks deletion during drag and before pending criteria have been accepted', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await ready();
    act(() => drag.start!());
    const button = screen.getByRole('button', { name: 'Delete Task 1' });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(api.actionItems.remove).not.toHaveBeenCalled();
    expect(window.confirm).not.toHaveBeenCalled();
    await act(async () =>
      drag.end!({ ...drop(), destination: null, reason: 'CANCEL' }),
    );
    fireEvent.change(screen.getByLabelText('Search action items'), {
      target: { value: 'unapplied filter' },
    });
    expect(
      screen.getByRole('button', { name: 'Delete Task 1' }),
    ).toBeDisabled();
    await act(async () => vi.advanceTimersByTime(300));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Delete Task 1' }),
      ).toBeEnabled(),
    );
  });

  it('blocks deletion after a failed refresh until a successful Retry', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await ready();
    vi.mocked(api.actionItems.list).mockRejectedValueOnce(
      new Error('Read failed'),
    );
    await act(async () => vi.advanceTimersByTime(POLL_INTERVAL_MS));
    await screen.findByRole('alert');
    const button = screen.getByRole('button', { name: 'Delete Task 1' });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(api.actionItems.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Delete Task 1' }),
      ).toBeEnabled(),
    );
  });

  it.each(['{Enter}', ' '])(
    'isolates %s keyboard activation from disclosure, navigation and drag',
    async (key) => {
      const user = userEvent.setup();
      const saving = deferred<{ deleted: boolean; id: number }>();
      vi.mocked(api.actionItems.remove).mockReturnValueOnce(saving.promise);
      await ready();
      const bubbled = vi.fn();
      window.addEventListener('keydown', bubbled);
      try {
        screen.getByRole('button', { name: 'Delete Task 1' }).focus();
        await user.keyboard(key);
        expect(api.actionItems.remove).toHaveBeenCalledTimes(1);
        expect(api.actionItems.remove).toHaveBeenCalledWith(1, 1);
        expect(bubbled).not.toHaveBeenCalled();
        expect(screen.getByRole('button', { name: 'Task 1' })).toHaveAttribute(
          'aria-expanded',
          'false',
        );
        expect(api.actionItems.get).not.toHaveBeenCalled();
        expect(api.actionItems.move).not.toHaveBeenCalled();
        await act(async () => saving.resolve({ deleted: true, id: 1 }));
      } finally {
        window.removeEventListener('keydown', bubbled);
      }
    },
  );
});

describe('Action item column sorting', () => {
  it('toggles visible columns and resets paging while retaining projects and filters without writes', async () => {
    vi.mocked(api.actionItems.list).mockResolvedValue({
      items: rows,
      total: 60,
    });
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: [
        '/action-items?project=Work&tags=security&limit=25&offset=25&sort=updated',
      ],
    });
    await screen.findByRole('button', { name: 'Task 1' });
    expect(
      screen.queryByRole('combobox', { name: 'Sort' }),
    ).not.toBeInTheDocument();
    for (const [label, ascending, descending] of [
      ['Title', 'title', 'title_desc'],
      ['Project', 'project_asc', 'project_desc'],
      ['Tags', 'tags_asc', 'tags_desc'],
      ['Due date', 'due_asc', 'due_desc'],
      ['Priority', 'manual', 'manual_desc'],
    ]) {
      fireEvent.click(screen.getByRole('button', { name: label }));
      await waitFor(() =>
        expect(api.actionItems.list).toHaveBeenLastCalledWith(
          expect.objectContaining({
            project: 'Work',
            tags: ['security'],
            sort: ascending,
            limit: 25,
            offset: 0,
          }),
        ),
      );
      fireEvent.click(screen.getByRole('button', { name: label }));
      await waitFor(() =>
        expect(api.actionItems.list).toHaveBeenLastCalledWith(
          expect.objectContaining({ sort: descending, offset: 0 }),
        ),
      );
    }
    expect(api.actionItems.move).not.toHaveBeenCalled();
    expect(api.actionItems.update).not.toHaveBeenCalled();
  });

  it('retains focused headers through a pending first page, failed sort, retry and empty result', async () => {
    const initial = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list).mockReturnValueOnce(initial.promise);
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: ['/action-items'],
    });
    const title = screen.getByRole('button', { name: 'Title' });
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    await act(async () => initial.resolve({ items: rows, total: 3 }));
    const sorted = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list).mockReturnValueOnce(sorted.promise);
    title.focus();
    fireEvent.click(title);
    expect(title).toHaveFocus();
    expect(
      screen.getByRole('columnheader', { name: 'Title' }),
    ).not.toHaveAttribute('aria-sort');
    await act(async () => sorted.reject(new Error('Sort request failed')));
    expect(title).toHaveFocus();
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'false');
    expect(
      screen.getByRole('columnheader', { name: 'Title' }),
    ).not.toHaveAttribute('aria-sort');
    vi.mocked(api.actionItems.list).mockResolvedValueOnce({
      items: [],
      total: 0,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() =>
      expect(
        screen.getByRole('columnheader', { name: 'Title' }),
      ).toHaveAttribute('aria-sort', 'ascending'),
    );
    expect(screen.getByRole('button', { name: 'Title' })).toBe(title);
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'false');
  });
});

it('keeps sorting quiet and reports pending retries while protecting retained rows from writes', async () => {
  await renderReady();
  const table = screen.getByRole('table');
  const title = screen.getByRole('button', { name: 'Title' });
  const pending = deferred<Paginated<ActionItemRow>>();
  vi.mocked(api.actionItems.list).mockReturnValueOnce(pending.promise);
  title.focus();
  fireEvent.click(title);
  expect(table).toHaveAttribute('aria-busy', 'true');
  expect(screen.getByRole('button', { name: 'Task 1' })).toBeInTheDocument();
  expect(
    screen.queryByText(
      /Loading action items|To drag items|Showing previous results/,
    ),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: 'Complete Task 1' }),
  ).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Delete Task 1' })).toBeDisabled();
  expect(
    screen.getByRole('button', { name: 'Move Task 1 to project' }),
  ).toBeDisabled();
  await act(async () => pending.reject(new Error('Unavailable sort read')));
  expect(table).toHaveAttribute('aria-busy', 'false');
  expect(
    screen.getByRole('columnheader', { name: 'Title' }),
  ).not.toHaveAttribute('aria-sort');
  const retry = deferred<Paginated<ActionItemRow>>();
  vi.mocked(api.actionItems.list).mockReturnValueOnce(retry.promise);
  fireEvent.click(title);
  expect(table).toHaveAttribute('aria-busy', 'true');
  expect(title).toHaveFocus();
  await act(async () => retry.resolve({ items: [], total: 0 }));
  expect(table).toHaveAttribute('aria-busy', 'false');
  expect(screen.getByRole('columnheader', { name: 'Title' })).toHaveAttribute(
    'aria-sort',
    'descending',
  );
  expect(screen.getByText('No open action items found.')).toBeVisible();
  expect(title).toHaveFocus();
  expect(api.actionItems.move).not.toHaveBeenCalled();
  expect(api.actionItems.update).not.toHaveBeenCalled();
  expect(api.actionItems.remove).not.toHaveBeenCalled();
});

it('announces a pending explicit Retry without replacing accepted rows or inserting loading prose', async () => {
  await renderReady();
  vi.mocked(api.actionItems.list).mockRejectedValueOnce(
    new Error('Unavailable sort read'),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Title' }));
  await screen.findByRole('alert');
  const table = screen.getByRole('table');
  expect(table).toHaveAttribute('aria-busy', 'false');
  const retry = deferred<Paginated<ActionItemRow>>();
  vi.mocked(api.actionItems.list).mockReturnValueOnce(retry.promise);
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await waitFor(() => expect(table).toHaveAttribute('aria-busy', 'true'));
  expect(screen.getByRole('button', { name: 'Task 1' })).toBeInTheDocument();
  expect(screen.queryByText('Loading action items…')).not.toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: 'Complete Task 1' }),
  ).toBeDisabled();
  await act(async () => retry.resolve({ items: [actionItem(1)], total: 1 }));
  expect(table).toHaveAttribute('aria-busy', 'false');
  expect(screen.getByRole('columnheader', { name: 'Title' })).toHaveAttribute(
    'aria-sort',
    'ascending',
  );
  expect(api.actionItems.update).not.toHaveBeenCalled();
});

describe('Action item boundary moves', () => {
  it.each([
    { edge: 'top', sort: 'manual', anchor: 1, scope: 'project=Work' },
    {
      edge: 'bottom',
      sort: 'manual_desc',
      anchor: 25,
      scope: 'unassigned=true',
    },
  ] as const)(
    'moves to $edge across pages while retaining every active filter',
    async ({ edge, sort, anchor, scope }) => {
      const page = [
        actionItem(11),
        actionItem(12, { revision: 7 }),
        actionItem(13),
      ];
      let moved = false;
      vi.mocked(api.actionItems.list).mockImplementation(async (filters) => ({
        items:
          filters?.limit === 1
            ? [actionItem(anchor)]
            : moved
              ? [page[0], page[2], actionItem(14)]
              : page,
        total: 25,
      }));
      vi.mocked(api.actionItems.move).mockImplementationOnce(async () => {
        moved = true;
        return actionItem(12, { revision: 8 });
      });
      renderWithProviders(<ActionItemsIndexPage />, {
        initialEntries: [
          `/action-items?${scope}&q=Task&tags=security,product&due_within_hours=24&offset=10`,
        ],
      });
      await screen.findByRole('button', { name: 'Task 12' });
      const currentFilters = vi.mocked(api.actionItems.list).mock.calls[0][0];
      expect(currentFilters).toMatchObject({
        status: 'open',
        sort: 'manual',
        q: 'Task',
        tags: ['security', 'product'],
        due_within_hours: 24,
        offset: 10,
        limit: 10,
        ...(edge === 'top' ? { project: 'Work' } : { unassigned: true }),
      });
      fireEvent.click(
        screen.getByRole('button', { name: `Move Task 12 to ${edge}` }),
      );
      await waitFor(() =>
        expect(api.actionItems.move).toHaveBeenCalledExactlyOnceWith(12, {
          expected_revision: 7,
          [edge === 'top' ? 'before_id' : 'after_id']: anchor,
        }),
      );
      await screen.findByRole('button', { name: 'Task 14' });
      expect(api.actionItems.list).toHaveBeenNthCalledWith(2, {
        ...currentFilters,
        sort,
        limit: 1,
        offset: 0,
      });
      expect(api.actionItems.list).toHaveBeenLastCalledWith(currentFilters);
      expect(screen.queryByRole('button', { name: 'Task 12' })).toBeNull();
    },
  );

  it.each([1, 3])(
    'disables redundant edges for a %i-item result',
    async (count) => {
      vi.mocked(api.actionItems.list).mockResolvedValue({
        items: rows.slice(0, count),
        total: count,
      });
      await renderReady();
      const top = screen.getByRole('button', { name: 'Move Task 1 to top' });
      const bottom = screen.getByRole('button', {
        name: `Move Task ${count} to bottom`,
      });
      expect(top).toBeDisabled();
      expect(bottom).toBeDisabled();
      if (count > 1) {
        expect(
          screen.getByRole('button', { name: 'Move Task 2 to top' }),
        ).toBeEnabled();
        expect(
          screen.getByRole('button', { name: 'Move Task 2 to bottom' }),
        ).toBeEnabled();
      }
      fireEvent.click(top);
      fireEvent.click(bottom);
      expect(api.actionItems.move).not.toHaveBeenCalled();
      expect(api.actionItems.list).toHaveBeenCalledTimes(1);
    },
  );

  it.each([
    '?sort=title',
    '?sort=manual_desc',
    '?status=completed',
    '?status=all',
  ])('omits manual move buttons in %s', async (query) => {
    renderWithProviders(<ActionItemsIndexPage />, {
      initialEntries: [`/action-items${query}`],
    });
    await screen.findByRole('button', { name: 'Task 1' });
    expect(
      screen.queryByRole('button', { name: /^Move Task \d+ to (top|bottom)$/ }),
    ).toBeNull();
    expect(api.actionItems.move).not.toHaveBeenCalled();
  });

  it('skips a self-anchor discovered after the displayed row changed position', async () => {
    await renderReady();
    vi.mocked(api.actionItems.list).mockResolvedValueOnce({
      items: [rows[1]],
      total: 3,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Move Task 2 to top' }));
    await waitFor(() => expect(api.actionItems.list).toHaveBeenCalledTimes(3));
    expect(api.actionItems.move).not.toHaveBeenCalled();
    expect(
      screen.getByRole('button', { name: 'Move Task 2 to top' }),
    ).toBeEnabled();
  });

  it('disables boundary controls during pending criteria and enables the accepted filtered result', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    const top = screen.getByRole('button', { name: 'Move Task 2 to top' });
    const bottom = screen.getByRole('button', {
      name: 'Move Task 2 to bottom',
    });
    expect(top).toBeEnabled();
    expect(bottom).toBeEnabled();
    fireEvent.change(screen.getByLabelText('Search action items'), {
      target: { value: 'Task' },
    });
    expect(top).toBeDisabled();
    expect(bottom).toBeDisabled();
    fireEvent.click(top);
    expect(api.actionItems.move).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: 'Task', offset: 0 }),
    );
    expect(top).toBeEnabled();
    expect(bottom).toBeEnabled();
  });

  it('freezes lookup, mutation and reconciliation, rejects repeated clicks, then resumes polling', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    const lookup = deferred<Paginated<ActionItemRow>>();
    const saving = deferred<ReturnType<typeof actionItem>>();
    const reread = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list)
      .mockReturnValueOnce(lookup.promise)
      .mockReturnValueOnce(reread.promise);
    vi.mocked(api.actionItems.move).mockReturnValueOnce(saving.promise);
    const top = screen.getByRole('button', { name: 'Move Task 2 to top' });
    fireEvent.click(top);
    fireEvent.click(top);
    fireEvent.click(
      screen.getByRole('button', { name: 'Move Task 1 to bottom' }),
    );
    expect(api.actionItems.list).toHaveBeenCalledTimes(2);
    expect(api.actionItems.move).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('Saving order…');
    for (const control of [
      top,
      screen.getByLabelText('Search action items'),
      screen.getByRole('button', { name: 'Title' }),
      screen.getByRole('button', { name: 'Complete Task 1' }),
      screen.getByRole('button', { name: 'Delete Task 1' }),
    ])
      expect(control).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
    });
    expect(api.actionItems.list).toHaveBeenCalledTimes(2);
    await act(async () => lookup.resolve({ items: [rows[0]], total: 3 }));
    expect(api.actionItems.move).toHaveBeenCalledExactlyOnceWith(2, {
      expected_revision: 1,
      before_id: 1,
    });
    expect(top).toBeDisabled();
    await act(async () => saving.resolve(actionItem(2, { revision: 2 })));
    expect(api.actionItems.list).toHaveBeenCalledTimes(3);
    expect(top).toBeDisabled();
    expect(screen.getByLabelText('Tags')).toBeDisabled();
    await act(async () => {
      reread.resolve({
        items: [
          actionItem(2, { revision: 2, priority: 1 }),
          actionItem(1, { priority: 2 }),
          rows[2],
        ],
        total: 3,
      });
    });
    expect(titles()).toEqual(['Task 2', 'Task 1', 'Task 3']);
    expect(screen.getByLabelText('Search action items')).toBeEnabled();
    expect(top).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Move Task 1 to top' }),
    ).toBeEnabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    });
    expect(api.actionItems.list).toHaveBeenCalledTimes(4);
    expect(api.actionItems.move).toHaveBeenCalledTimes(1);
  });

  it.each(['lookup', 'move', 'empty boundary'])(
    'reports a %s failure, reconciles without replaying, and resumes polling',
    async (stage) => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      renderWithProviders(
        <>
          <ActionItemsIndexPage />
          <NotificationBar />
        </>,
        { initialEntries: ['/action-items'] },
      );
      await screen.findByRole('button', { name: 'Task 1' });
      if (stage === 'lookup')
        vi.mocked(api.actionItems.list).mockRejectedValueOnce(
          new Error('Boundary unavailable'),
        );
      else {
        vi.mocked(api.actionItems.list).mockResolvedValueOnce({
          items: stage === 'empty boundary' ? [] : [rows[0]],
          total: stage === 'empty boundary' ? 0 : 3,
        });
        if (stage === 'move')
          vi.mocked(api.actionItems.move).mockRejectedValueOnce(
            new ApiError('Source changed', 409),
          );
      }
      fireEvent.click(
        screen.getByRole('button', { name: 'Move Task 2 to top' }),
      );
      await screen.findByRole('alert');
      await waitFor(() =>
        expect(
          screen.getByRole('button', { name: 'Move Task 2 to top' }),
        ).toBeEnabled(),
      );
      if (stage === 'lookup')
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Boundary unavailable',
        );
      if (stage === 'move')
        expect(screen.getByRole('alert')).toHaveTextContent('Source changed');
      expect(api.actionItems.move).toHaveBeenCalledTimes(
        stage === 'move' ? 1 : 0,
      );
      expect(api.actionItems.list).toHaveBeenCalledTimes(3);
      expect(titles()).toEqual(['Task 1', 'Task 2', 'Task 3']);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
      });
      expect(api.actionItems.list).toHaveBeenCalledTimes(4);
      expect(api.actionItems.move).toHaveBeenCalledTimes(
        stage === 'move' ? 1 : 0,
      );
    },
  );

  it('blocks edge moves after a failed reconciliation until explicit Retry succeeds', async () => {
    await renderReady();
    vi.mocked(api.actionItems.list)
      .mockResolvedValueOnce({ items: [rows[0]], total: 3 })
      .mockRejectedValueOnce(new Error('Reread failed'));
    fireEvent.click(screen.getByRole('button', { name: 'Move Task 2 to top' }));
    await screen.findByRole('alert');
    expect(
      screen.getByRole('button', { name: 'Move Task 2 to top' }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Move Task 2 to top' }));
    expect(api.actionItems.move).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Move Task 2 to top' }),
      ).toBeEnabled(),
    );
    expect(api.actionItems.move).toHaveBeenCalledTimes(1);
  });

  it.each([{ revision: 2 }, { priority: 5 }])(
    'rejects an in-flight poll that changes the source snapshot: %j',
    async (change) => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      await renderReady();
      const polling = deferred<Paginated<ActionItemRow>>();
      const lookup = deferred<Paginated<ActionItemRow>>();
      vi.mocked(api.actionItems.list)
        .mockReturnValueOnce(polling.promise)
        .mockReturnValueOnce(lookup.promise);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
      });
      fireEvent.click(
        screen.getByRole('button', { name: 'Move Task 2 to top' }),
      );
      await act(async () => {
        polling.resolve({
          items: [rows[0], actionItem(2, change), rows[2]],
          total: 3,
        });
      });
      await act(async () => lookup.resolve({ items: [rows[0]], total: 3 }));
      expect(api.actionItems.move).not.toHaveBeenCalled();
      expect(api.actionItems.list).toHaveBeenCalledTimes(4);
      expect(
        screen.getByRole('button', { name: 'Move Task 2 to top' }),
      ).toBeEnabled();
    },
  );

  it('does not mutate or reread after unmounting during a boundary lookup', async () => {
    const rendered = await renderReady();
    const lookup = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list).mockReturnValueOnce(lookup.promise);
    fireEvent.click(screen.getByRole('button', { name: 'Move Task 2 to top' }));
    rendered.unmount();
    await act(async () => lookup.resolve({ items: [rows[0]], total: 3 }));
    expect(api.actionItems.move).not.toHaveBeenCalled();
    expect(api.actionItems.list).toHaveBeenCalledTimes(2);
  });

  it('abandons an obsolete boundary lookup when external navigation changes the current filters', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(
      <>
        <Link to="/action-items?q=Changed">Change view</Link>
        <ActionItemsIndexPage />
      </>,
      { initialEntries: ['/action-items'] },
    );
    await screen.findByRole('button', { name: 'Task 1' });
    const lookup = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list)
      .mockReturnValueOnce(lookup.promise)
      .mockResolvedValue({ items: [actionItem(9)], total: 1 });
    fireEvent.click(screen.getByRole('button', { name: 'Move Task 2 to top' }));
    fireEvent.click(screen.getByRole('link', { name: 'Change view' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    await screen.findByRole('button', { name: 'Task 9' });
    await act(async () => lookup.resolve({ items: [rows[0]], total: 3 }));
    expect(api.actionItems.move).not.toHaveBeenCalled();
    expect(api.actionItems.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: 'Changed', offset: 0 }),
    );
    expect(titles()).toEqual(['Task 9']);
  });
});
