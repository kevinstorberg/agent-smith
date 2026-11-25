import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  api,
  ApiError,
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
  return renderHook(
    ({ activeFilters, activePage, pending }) =>
      useActionItemGroupedQueue({
        filters: activeFilters,
        criteria: JSON.stringify(activeFilters),
        viewKey: JSON.stringify(activeFilters),
        reorderableView: true,
        criteriaPending: pending,
        pagination: { page: activePage, onPageChange: vi.fn() },
      }),
    {
      initialProps: {
        activeFilters: filters,
        activePage: page,
        pending: false,
      },
    },
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

const dragFilters: ActionItemQueueFilters = {
  kind: 'all',
  status: 'open',
  sort: 'manual',
};
const childDrag = {
  draggableId: 'item:2',
  type: 'EPIC:10',
  mode: 'SNAP' as const,
  source: { droppableId: 'epic:10', index: 0 },
};
const childDrop = {
  ...childDrag,
  reason: 'DROP' as const,
  destination: null,
  combine: null,
};

function dragPage() {
  return {
    items: [epicGroup(10, [child]), epicGroup(20, [])],
    total: 2,
    matching_count: 1,
  };
}

afterEach(() => {
  document
    .querySelectorAll('[data-test-drag-surface]')
    .forEach((element) => element.remove());
});

async function renderMembershipDrag() {
  const page = dragPage();
  vi.mocked(api.actionItemQueue.list).mockResolvedValue(page);
  const hook = renderQueue(dragFilters);
  await waitFor(() => expect(hook.result.current.canAct()).toBe(true));
  const surface = document.createElement('div');
  surface.dataset.testDragSurface = 'true';
  const targets = [10, 20, 'none'].map((id, index) => {
    const element = document.createElement('section');
    element.dataset.epicDropTarget = String(id);
    vi.spyOn(element, 'getBoundingClientRect').mockReturnValue(
      new DOMRect(0, 100 + index * 150, 200, 100),
    );
    surface.append(element);
    return element;
  });
  const tabs = document.createElement('div');
  const project = document.createElement('button');
  project.dataset.projectId = '40';
  project.dataset.projectName = 'Another project';
  tabs.append(project);
  surface.append(tabs);
  document.body.append(surface);
  hook.result.current.epicTargetsRef.current = surface;
  hook.result.current.projectTabsRef.current = tabs;
  return { ...hook, page, surface, targets };
}

function key(key: string, shiftKey = false) {
  act(() =>
    window.dispatchEvent(
      new KeyboardEvent('keydown', { key, shiftKey, bubbles: true }),
    ),
  );
}

function selectOtherEpic(result: ReturnType<typeof renderQueue>['result']) {
  act(() => result.current.startDrag(childDrag));
  key('ArrowRight', true);
  expect(result.current.snapshot?.epicTarget?.epic?.id).toBe(20);
}

function expectNoDragWrite() {
  expect(api.actionItemQueue.setEpic).not.toHaveBeenCalled();
  expect(api.actionItemQueue.move).not.toHaveBeenCalled();
  expect(api.actionItems.update).not.toHaveBeenCalled();
}

describe('cross-Epic drag admission and cancellation', () => {
  it.each(['CANCEL', 'outside', 'same parent'] as const)(
    'does not write after %s',
    async (reason) => {
      const { result } = await renderMembershipDrag();
      if (reason === 'same parent') {
        act(() => result.current.startDrag({ ...childDrag, mode: 'FLUID' }));
        expect(
          result.current.snapshot?.epics?.some(
            (target) => target.epic?.id === 10,
          ),
        ).toBe(false);
        act(() =>
          window.dispatchEvent(
            new MouseEvent('mouseup', { clientX: 50, clientY: 150 }),
          ),
        );
        expect(result.current.snapshot?.epicTarget).toBeNull();
      } else {
        selectOtherEpic(result);
        key(reason === 'CANCEL' ? 'Escape' : 'ArrowDown');
        expect(result.current.snapshot?.epicTarget).toBeNull();
      }
      await act(async () =>
        result.current.endDrag({
          ...childDrop,
          reason: reason === 'CANCEL' ? 'CANCEL' : 'DROP',
        }),
      );
      expectNoDragWrite();
      expect(result.current.snapshot).toBeNull();
    },
  );

  it.each(['pending filters', 'new filters', 'new page'] as const)(
    'rejects a captured destination after %s',
    async (change) => {
      const { result, rerender } = await renderMembershipDrag();
      selectOtherEpic(result);
      rerender({
        activeFilters:
          change === 'new filters'
            ? { ...dragFilters, q: 'other' }
            : dragFilters,
        activePage: { limit: 10, offset: change === 'new page' ? 10 : 0 },
        pending: change === 'pending filters',
      });
      await act(async () => result.current.endDrag(childDrop));
      expectNoDragWrite();
      expect(result.current.snapshot).toBeNull();
    },
  );

  it.each(['source', 'destination'] as const)(
    'rejects %s drift even when the target DOM stays connected',
    async (changed) => {
      const { result } = await renderMembershipDrag();
      selectOtherEpic(result);
      const fresh = dragPage();
      if (changed === 'source')
        fresh.items[0].children[0].item = { ...child, revision: 2 };
      else
        fresh.items[1].epic = {
          ...fresh.items[1].epic,
          revision: 4,
          cohort: 'changed-destination',
        };
      vi.mocked(api.actionItemQueue.list).mockResolvedValue(fresh);
      await act(async () => result.current.refresh({ showLoading: false }));
      await act(async () => result.current.endDrag(childDrop));
      expectNoDragWrite();
      expect(result.current.snapshot).toBeNull();
    },
  );

  it('rejects an uncompleted read rather than writing from the prior view', async () => {
    const { result, rerender, page } = await renderMembershipDrag();
    selectOtherEpic(result);
    const read = deferred<ActionItemGroupedPage>();
    vi.mocked(api.actionItemQueue.list)
      .mockReturnValueOnce(read.promise)
      .mockResolvedValue(page);
    rerender({
      activeFilters: { ...dragFilters, tags: ['new'] },
      activePage: { limit: 10, offset: 0 },
      pending: false,
    });
    await waitFor(() =>
      expect(api.actionItemQueue.list).toHaveBeenCalledTimes(2),
    );
    expect(result.current.dataCurrent).toBe(false);
    await act(async () => result.current.endDrag(childDrop));
    expectNoDragWrite();
    await act(async () => read.resolve(page));
    expect(result.current.snapshot).toBeNull();
  });

  it('requires a fresh explicit gesture after a conflict and uses its new destination reference', async () => {
    const { result } = await renderMembershipDrag();
    selectOtherEpic(result);
    const fresh = dragPage();
    fresh.items[1].epic = {
      ...fresh.items[1].epic,
      revision: 4,
      cohort: 'new-cohort',
    };
    vi.mocked(api.actionItemQueue.list).mockResolvedValue(fresh);
    vi.mocked(api.actionItemQueue.setEpic)
      .mockRejectedValueOnce(new ApiError('Epic changed', 409))
      .mockResolvedValue(child);
    await act(async () => result.current.endDrag(childDrop));
    expect(api.actionItemQueue.setEpic).toHaveBeenCalledTimes(1);
    expect(result.current.reviewError).toBe('Epic changed');
    expect(result.current.snapshot).toBeNull();
    expect(api.actionItemQueue.setEpic).toHaveBeenLastCalledWith(2, {
      expected_revision: child.revision,
      expected_parent: { id: 10, expected_revision: 3, cohort: 'cohort-10' },
      destination: { id: 20, expected_revision: 3, cohort: 'cohort-20' },
    });
    selectOtherEpic(result);
    await act(async () => result.current.endDrag(childDrop));
    expect(api.actionItemQueue.setEpic).toHaveBeenCalledTimes(2);
    expect(api.actionItemQueue.setEpic).toHaveBeenLastCalledWith(2, {
      expected_revision: child.revision,
      expected_parent: { id: 10, expected_revision: 3, cohort: 'cohort-10' },
      destination: { id: 20, expected_revision: 4, cohort: 'new-cohort' },
    });
    expect(api.actionItemQueue.move).not.toHaveBeenCalled();
  });

  it('keeps duplicate drops single flight through canonical refresh', async () => {
    const { result } = await renderMembershipDrag();
    selectOtherEpic(result);
    const save = deferred<typeof child>();
    vi.mocked(api.actionItemQueue.setEpic).mockReturnValueOnce(save.promise);
    let first: Promise<void>;
    act(() => {
      first = result.current.endDrag(childDrop);
    });
    await waitFor(() => expect(result.current.busy).toBe(true));
    await act(async () => result.current.endDrag(childDrop));
    expect(api.actionItemQueue.setEpic).toHaveBeenCalledTimes(1);
    expect(result.current.snapshot?.epicTarget).toBeUndefined();
    await act(async () => {
      save.resolve(child);
      await first;
    });
    expect(api.actionItemQueue.setEpic).toHaveBeenCalledTimes(1);
    expect(api.actionItemQueue.list).toHaveBeenCalledTimes(2);
    expect(result.current.snapshot).toBeNull();
  });

  it('keeps project and Epic keyboard choices mutually exclusive and clears both for ordering', async () => {
    const { result } = await renderMembershipDrag();
    selectOtherEpic(result);
    key('ArrowRight');
    expect(result.current.snapshot?.project).toBe('Another project');
    expect(result.current.snapshot?.epicTarget).toBeNull();
    key('ArrowRight', true);
    expect(result.current.snapshot?.project).toBeNull();
    expect(result.current.snapshot?.epicTarget?.epic?.id).toBe(20);
    key('ArrowUp');
    expect(result.current.snapshot?.project).toBeNull();
    expect(result.current.snapshot?.epicTarget).toBeNull();
    await act(async () => result.current.endDrag(childDrop));
    expectNoDragWrite();
  });

  it.each([true, false])(
    'uses final mouseup geometry with inside=%s even without an intermediate move',
    async (inside) => {
      const { result } = await renderMembershipDrag();
      act(() => result.current.startDrag({ ...childDrag, mode: 'FLUID' }));
      if (!inside)
        act(() =>
          window.dispatchEvent(
            new MouseEvent('mousemove', { clientX: 50, clientY: 300 }),
          ),
        );
      act(() =>
        window.dispatchEvent(
          new MouseEvent('mouseup', {
            clientX: inside ? 50 : 500,
            clientY: inside ? 300 : 600,
          }),
        ),
      );
      expect(result.current.snapshot?.epicTarget?.epic?.id ?? null).toBe(
        inside ? 20 : null,
      );
      await act(async () =>
        result.current.endDrag({ ...childDrop, mode: 'FLUID' }),
      );
      if (inside)
        expect(api.actionItemQueue.setEpic).toHaveBeenCalledExactlyOnceWith(2, {
          expected_revision: child.revision,
          expected_parent: {
            id: 10,
            expected_revision: 3,
            cohort: 'cohort-10',
          },
          destination: { id: 20, expected_revision: 3, cohort: 'cohort-20' },
        });
      else expectNoDragWrite();
      expect(api.actionItemQueue.move).not.toHaveBeenCalled();
    },
  );
});

describe('explicit root ordering with filtered-out roots', () => {
  it.each(['before', 'after'] as const)(
    'sends the exact %s anchor even when the visible order is unchanged',
    async (edge) => {
      const { result, surface } = await renderMembershipDrag();
      const first = epicGroup(10, []);
      const last = epicGroup(20, []);
      first.epic.position = 1;
      last.epic.position = 10;
      const source = { ...singleEntry(), position: 4 };
      vi.mocked(api.actionItemQueue.list).mockResolvedValue({
        items: [first, source, last],
        total: 3,
        matching_count: 1,
      });
      await act(async () => result.current.refresh({ showLoading: false }));
      const anchor = edge === 'after' ? first.epic : last.epic;
      const target = document.createElement('span');
      target.dataset.rootOrderId = `epic:${anchor.id}`;
      target.dataset.rootOrderEdge = edge;
      vi.spyOn(target, 'getBoundingClientRect').mockReturnValue(
        new DOMRect(0, 210, 200, 20),
      );
      surface.append(target);
      const start = {
        draggableId: 'item:9',
        type: 'ROOT',
        mode: 'FLUID' as const,
        source: { droppableId: 'action-items', index: 1 },
      };
      act(() => result.current.startDrag(start));
      act(() =>
        window.dispatchEvent(
          new MouseEvent('mouseup', { clientX: 50, clientY: 220 }),
        ),
      );
      expect(result.current.snapshot?.rootOrderTarget?.edge).toBe(edge);
      await act(async () =>
        result.current.endDrag({
          ...start,
          reason: 'DROP',
          destination: null,
          combine: null,
        }),
      );
      expect(api.actionItemQueue.move).toHaveBeenCalledExactlyOnceWith({
        source: { kind: 'item', id: 9, expected_revision: single.revision },
        [edge]: {
          kind: 'epic',
          id: anchor.id,
          expected_revision: anchor.revision,
          cohort: anchor.cohort,
        },
      });
      expect(api.actionItemQueue.setEpic).not.toHaveBeenCalled();
      expect(api.actionItems.update).not.toHaveBeenCalled();
    },
  );
});
