import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  api,
  type ActionItemGroupedPage,
  type ActionItemQueueFilters,
} from '../../api';
import { useActionItemGroupedQueue } from '../useActionItemGroupedQueue';
import { actionItem, deferred } from '../../pages/__tests__/actionItemFixture';
import {
  epicGroup,
  taskEntry,
  taskPage,
} from '../../pages/__tests__/actionItemEpicFixture';

const child = actionItem(2, { priority: 7 });
const single = actionItem(9, { priority: 12 });
const parent = { ...epicGroup().epic, open_count: 8 };
const childEntry = () =>
  taskEntry(child, { parent, rootIndex: 0, position: 4 });
const singleEntry = () =>
  taskEntry(single, { parent: null, rootIndex: 1, position: 3 });
const projection = () =>
  taskPage({ items: [childEntry(), singleEntry()], total: 2, root_total: 2 });

function renderQueue(
  filters: ActionItemQueueFilters = {
    kind: 'task',
    status: 'open',
    sort: 'manual',
    project: 'Work',
  },
  page = { limit: 10, offset: 0 },
) {
  return renderHook(() =>
    useActionItemGroupedQueue({
      filters,
      criteria: JSON.stringify(filters),
      viewKey: JSON.stringify(filters),
      reorderableView: true,
      criteriaPending: false,
      pagination: { page, onPageChange: vi.fn() },
    }),
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api.actionItemQueue, 'list').mockResolvedValue(projection());
  vi.spyOn(api.actionItemQueue, 'move').mockResolvedValue({ saved: true });
  vi.spyOn(api.actionItemQueue, 'setEpic').mockResolvedValue(child);
  vi.spyOn(api.actionItemEpics, 'list').mockResolvedValue({ items: [parent] });
  vi.spyOn(api.actionItems, 'update').mockResolvedValue({
    ...child,
    description: '',
  });
});

describe('parent-aware Action Item task projection', () => {
  it.each(['none', 'another Epic'] as const)(
    'moves a flat child to %s using its displayed parent snapshot',
    async (target) => {
      const destination =
        target === 'none'
          ? null
          : { ...parent, id: 20, revision: 9, cohort: 'chosen-destination' };
      const { result } = renderQueue();
      await waitFor(() => expect(result.current.canAct()).toBe(true));
      await act(async () => {
        await result.current.setEpic(child, destination);
      });
      expect(api.actionItemQueue.setEpic).toHaveBeenCalledExactlyOnceWith(2, {
        expected_revision: 1,
        expected_parent: { id: 10, expected_revision: 3, cohort: 'cohort-10' },
        destination: destination
          ? { id: 20, expected_revision: 9, cohort: 'chosen-destination' }
          : null,
      });
      expect(api.actionItemEpics.list).not.toHaveBeenCalled();
    },
  );

  it('keeps completed flat tasks organized without offering open-sibling order actions', async () => {
    const completed = actionItem(2, {
      status: 'completed',
      priority: null,
      revision: 7,
    });
    const owner = { ...parent, open_count: 0 };
    const entry = taskEntry(completed, {
      parent: owner,
      rootIndex: 0,
      position: null,
    });
    vi.mocked(api.actionItemQueue.list).mockResolvedValue(
      taskPage({ items: [entry], total: 1, root_total: 1 }),
    );
    const { result } = renderQueue({ kind: 'task', status: 'completed' });
    await waitFor(() => expect(result.current.canAct()).toBe(true));
    expect(result.current.displayPriority(entry)).toBeNull();
    expect(result.current.parentEpic(completed)).toEqual(owner);
    expect(result.current.canMoveToEdge(completed, 'top')).toBe(false);
    expect(result.current.canMoveToEdge(completed, 'bottom')).toBe(false);
    await act(async () => {
      await result.current.setEpic(completed, null);
    });
    expect(api.actionItemQueue.setEpic).toHaveBeenCalledExactlyOnceWith(2, {
      expected_revision: 7,
      expected_parent: { id: 10, expected_revision: 3, cohort: 'cohort-10' },
      destination: null,
    });
  });

  it.each(['CANCEL', 'DROP'] as const)(
    'clears a captured grouped drag after external task-view navigation and %s without writing',
    async (reason) => {
      vi.mocked(api.actionItemQueue.list).mockImplementation(async (filters) =>
        filters?.kind === 'task'
          ? projection()
          : {
              items: [epicGroup(), singleEntry()],
              total: 2,
              matching_count: 2,
            },
      );
      const { result, rerender } = renderHook(
        ({ kind }: { kind: 'all' | 'task' }) => {
          const filters: ActionItemQueueFilters = {
            kind,
            status: 'open',
            sort: 'manual',
            project: 'Work',
          };
          return useActionItemGroupedQueue({
            filters,
            criteria: JSON.stringify(filters),
            viewKey: JSON.stringify(filters),
            reorderableView: true,
            criteriaPending: false,
            pagination: {
              page: { limit: 10, offset: 0 },
              onPageChange: vi.fn(),
            },
          });
        },
        { initialProps: { kind: 'all' as 'all' | 'task' } },
      );
      await waitFor(() => expect(result.current.canAct()).toBe(true));
      act(() =>
        result.current.startDrag({
          draggableId: 'epic:10',
          type: 'ROOT',
          mode: 'SNAP',
          source: { droppableId: 'action-items', index: 0 },
        }),
      );
      expect(result.current.snapshot).not.toBeNull();
      rerender({ kind: 'task' });
      await waitFor(() => expect(result.current.dataCurrent).toBe(true));
      await act(async () => {
        await result.current.endDrag({
          draggableId: 'epic:10',
          type: 'ROOT',
          mode: 'SNAP',
          reason,
          source: { droppableId: 'action-items', index: 0 },
          destination: { droppableId: 'action-items', index: 1 },
          combine: null,
        });
      });
      expect(result.current.snapshot).toBeNull();
      expect(result.current.freezeControls).toBe(false);
      expect(result.current.taskView).toBe(true);
      expect(result.current.canDrag).toBe(false);
      expect(result.current.roots.every((entry) => entry.kind === 'item')).toBe(
        true,
      );
      expect(api.actionItemQueue.move).not.toHaveBeenCalled();
      expect(api.actionItemQueue.setEpic).not.toHaveBeenCalled();
      expect(api.actionItems.update).not.toHaveBeenCalled();
    },
  );

  it('keeps global display ranks distinct from sibling positions and disables flat dragging', async () => {
    const { result } = renderQueue();
    await waitFor(() => expect(result.current.canAct()).toBe(true));
    expect(result.current.taskView).toBe(true);
    expect(result.current.displayPriority(childEntry())).toBe(7);
    expect(childEntry().position).toBe(4);
    expect(result.current.parentEpic(child)).toEqual(parent);
    expect(result.current.parentId(single)).toBeNull();
    expect(result.current.canMoveToEdge(child, 'top')).toBe(true);
    expect(result.current.canMoveToEdge(child, 'bottom')).toBe(true);
    expect(result.current.moveScopeLabel(child, 'top')).toBe(
      'Move to top of Epic Release',
    );
    expect(result.current.moveScopeLabel(single, 'bottom')).toBe(
      'Move to bottom of matching list',
    );
    expect(result.current.canDrag).toBe(false);
    expect(result.current.dragSurfaceEnabled).toBe(false);
    expect(result.current.projectAssignment).toBe(false);
    act(() => result.current.startDrag());
    expect(result.current.snapshot).toBeNull();
    expect(api.actionItemQueue.move).not.toHaveBeenCalled();
  });

  it.each(['top', 'bottom'] as const)(
    'moves a filtered middle child to its true Epic %s with frozen source context',
    async (edge) => {
      const { result } = renderQueue();
      await waitFor(() => expect(result.current.canAct()).toBe(true));
      await act(async () => {
        await result.current.moveToEdge(child, edge);
      });
      expect(api.actionItemQueue.move).toHaveBeenCalledExactlyOnceWith({
        source: { kind: 'item', id: 2, expected_revision: 1 },
        parent: { id: 10, expected_revision: 3, cohort: 'cohort-10' },
        edge,
      });
      expect(api.actionItemQueue.list).toHaveBeenCalledTimes(2);
    },
  );

  it('uses root metadata rather than task counts and maps a task-view boundary child to its Epic', async () => {
    vi.mocked(api.actionItemQueue.list)
      .mockResolvedValueOnce(
        taskPage({ items: [singleEntry()], total: 100, root_total: 2 }),
      )
      .mockResolvedValueOnce(
        taskPage({ items: [childEntry()], total: 100, root_total: 2 }),
      )
      .mockResolvedValue(projection());
    const { result } = renderQueue(
      {
        kind: 'task',
        status: 'open',
        sort: 'manual',
        project: 'Work',
        q: 'review',
      },
      { limit: 1, offset: 99 },
    );
    await waitFor(() => expect(result.current.canAct()).toBe(true));
    expect(result.current.canMoveToEdge(single, 'top')).toBe(true);
    expect(result.current.canMoveToEdge(single, 'bottom')).toBe(false);
    await act(async () => {
      await result.current.moveToEdge(single, 'top');
    });
    expect(vi.mocked(api.actionItemQueue.list).mock.calls[1][0]).toEqual({
      kind: 'task',
      status: 'open',
      sort: 'manual',
      project: 'Work',
      q: 'review',
      limit: 1,
      offset: 0,
    });
    expect(api.actionItemQueue.move).toHaveBeenCalledExactlyOnceWith({
      source: { kind: 'item', id: 9, expected_revision: 1 },
      before: {
        kind: 'epic',
        id: 10,
        expected_revision: 3,
        cohort: 'cohort-10',
      },
    });
  });

  it('does not write when parent context changes while a root boundary probe is pending', async () => {
    const boundary = deferred<ActionItemGroupedPage>();
    const changed = projection();
    changed.items[0].parent = { ...parent, cohort: 'changed-hidden-members' };
    vi.mocked(api.actionItemQueue.list)
      .mockResolvedValueOnce(projection())
      .mockReturnValueOnce(boundary.promise)
      .mockResolvedValue(changed);
    const { result } = renderQueue();
    await waitFor(() => expect(result.current.canAct()).toBe(true));
    let moving!: Promise<void>;
    act(() => {
      moving = result.current.moveToEdge(single, 'top');
    });
    await act(async () => {
      await result.current.refresh({ showLoading: false });
    });
    await act(async () => {
      boundary.resolve(projection());
      await moving;
    });
    expect(api.actionItemQueue.move).not.toHaveBeenCalled();
  });

  it.each(['parent', 'root_total', 'root_index', 'parent identity'] as const)(
    'fails closed for missing or inconsistent %s',
    async (field) => {
      const malformed = projection();
      if (field === 'parent')
        delete (malformed.items[0] as { parent?: unknown }).parent;
      if (field === 'root_total')
        delete (malformed as { root_total?: number }).root_total;
      if (field === 'root_index') malformed.items[0].root_index = 2;
      if (field === 'parent identity') malformed.items[0].parent_epic_id = 999;
      vi.mocked(api.actionItemQueue.list).mockResolvedValue(malformed);
      const { result } = renderQueue();
      await waitFor(() =>
        expect(result.current.error).toContain(
          'membership context is incomplete',
        ),
      );
      expect(result.current.canAct()).toBe(false);
      await act(async () => {
        await result.current.setEpic(child, null);
      });
      expect(api.actionItemQueue.setEpic).not.toHaveBeenCalled();
    },
  );

  it('ungroups without catalog access, locks duplicate requests, and explains a task hidden by Epics-only filtering', async () => {
    const group = epicGroup();
    const removed = epicGroup(10, []);
    const saving = deferred<typeof child>();
    vi.mocked(api.actionItemQueue.list)
      .mockResolvedValueOnce({ items: [group], total: 1, matching_count: 1 })
      .mockResolvedValue({ items: [removed], total: 1, matching_count: 0 });
    vi.mocked(api.actionItemQueue.setEpic).mockReturnValueOnce(saving.promise);
    vi.mocked(api.actionItemEpics.list).mockRejectedValue(
      new Error('Catalog unavailable'),
    );
    const { result } = renderQueue({
      kind: 'epic',
      status: 'open',
      sort: 'manual',
    });
    await waitFor(() => expect(result.current.canAct()).toBe(true));
    let moving!: ReturnType<typeof result.current.setEpic>;
    act(() => {
      moving = result.current.setEpic(group.children[0].item, null);
      void result.current.setEpic(group.children[0].item, null);
    });
    expect(api.actionItemQueue.setEpic).toHaveBeenCalledExactlyOnceWith(2, {
      expected_revision: 1,
      expected_parent: { id: 10, expected_revision: 3, cohort: 'cohort-10' },
      destination: null,
    });
    await act(async () => {
      saving.resolve(child);
      await moving;
    });
    expect(result.current.membershipNotice).toEqual({
      itemId: 2,
      title: 'Task 2',
      epicTitle: 'Release',
    });
    expect(api.actionItemEpics.list).not.toHaveBeenCalled();
    act(() => result.current.clearMembershipNotice());
    expect(result.current.membershipNotice).toBeNull();
  });
});
