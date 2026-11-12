import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { DragStart, DropResult } from '@hello-pangea/dnd';
import type {
  ActionItem,
  ActionItemFilters,
  ActionItemMove,
  ActionItemPatch,
  ActionItemRow,
  Paginated,
} from '../api';
import type { PaginationOptions } from './usePagination';
import { usePagination } from './usePagination';
import { usePolling } from './usePolling';
import { useNotification } from '../context/useNotification';

export interface ActionItemQueueSource {
  list: (filters: ActionItemFilters) => Promise<Paginated<ActionItemRow>>;
  get: (id: number) => Promise<ActionItem>;
  update: (id: number, body: ActionItemPatch) => Promise<ActionItem>;
  move: (id: number, body: ActionItemMove) => Promise<ActionItem>;
}
interface DragSnapshot {
  items: ActionItemRow[];
  view: string;
  projects?: ProjectTarget[];
  project?: string | null;
  mode?: DragStart['mode'];
  itemId?: string;
}

interface ProjectTarget {
  id: string;
  name: string;
  button: HTMLButtonElement;
}

function projectTargets(tabs: HTMLDivElement | null): ProjectTarget[] {
  return Array.from(
    tabs?.querySelectorAll<HTMLButtonElement>('button[data-project-id]') ?? [],
    (button) => ({
      id: button.dataset.projectId!,
      name: button.dataset.projectName!,
      button,
    }),
  );
}

function projectAtPoint(
  tabs: HTMLDivElement | null,
  targets: ProjectTarget[],
  x: number,
  y: number,
) {
  const strip = tabs?.getBoundingClientRect();
  if (
    !strip ||
    x < strip.left ||
    x > strip.right ||
    y < strip.top ||
    y > strip.bottom
  )
    return null;
  return (
    targets.find(({ button }) => {
      const rect = button.getBoundingClientRect();
      return (
        button.isConnected &&
        rect.width > 0 &&
        rect.height > 0 &&
        x >= rect.left &&
        x <= rect.right &&
        y >= rect.top &&
        y <= rect.bottom
      );
    })?.name ?? null
  );
}

export function useActionItemQueue({
  source,
  removeRow,
  filters,
  criteria,
  viewKey,
  reorderableView,
  projectAssignment = false,
  criteriaPending = false,
  active = true,
  disabled = false,
  editing = false,
  noun = 'action item',
  pagination,
}: {
  source: ActionItemQueueSource;
  removeRow?: (id: number, expectedRevision: number) => Promise<unknown>;
  filters: ActionItemFilters;
  criteria: string;
  viewKey: string;
  reorderableView: boolean;
  projectAssignment?: boolean;
  criteriaPending?: boolean;
  active?: boolean;
  disabled?: boolean;
  editing?: boolean;
  noun?: string;
  pagination?: PaginationOptions;
}) {
  const [snapshot, setSnapshot] = useState<DragSnapshot | null>(null);
  const drag = useRef<DragSnapshot | null>(null);
  const orderFocus = useRef<{
    handle: HTMLButtonElement | null;
    fallback?: HTMLElement;
    view: string;
  } | null>(null);
  const projectTabsRef = useRef<HTMLDivElement>(null);
  const [savingOrder, setSavingOrder] = useState(false);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const writing = useRef(false);
  const { notify } = useNotification();
  const readItems = (overrides: ActionItemFilters) =>
    source.list({ ...filters, ...overrides });
  const list = usePagination<ActionItemRow>(
    (limit, offset) => readItems({ limit, offset }),
    [criteria],
    10,
    pagination,
  );
  const {
    items,
    total,
    loading,
    error,
    limit,
    offset,
    setOffset,
    refresh,
    setItems,
  } = list;
  const latestRefresh = useRef(refresh);
  const mounted = useRef(false);
  useLayoutEffect(() => {
    latestRefresh.current = refresh;
  }, [refresh]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const view = JSON.stringify([viewKey, limit, offset]);
  const [expanded, setExpanded] = useState<{ id: number; view: string } | null>(
    null,
  );
  const expandedId = expanded?.view === view ? expanded.id : null;
  useEffect(() => {
    if (expanded && expanded.view !== view) setExpanded(null);
  }, [expanded, view]);
  const readableView =
    !criteriaPending &&
    list.dataCurrent &&
    !loading &&
    !error &&
    active &&
    !disabled &&
    !editing;
  const orderCurrent = reorderableView && readableView;
  const current = useRef({ view, items, source, orderCurrent });
  useLayoutEffect(() => {
    current.current = { view, items, source, orderCurrent };
  });
  const busy = savingOrder || pendingId !== null || editing;
  useEffect(() => {
    if (busy || snapshot) return;
    const focus = orderFocus.current;
    orderFocus.current = null;
    const handle =
      focus?.view !== current.current.view
        ? null
        : focus?.handle?.isConnected && !focus.handle.disabled
          ? focus.handle
          : focus?.fallback;
    if (
      handle?.isConnected &&
      !(handle instanceof HTMLButtonElement && handle.disabled) &&
      document.activeElement === document.body
    )
      handle.focus({ preventScroll: true });
  }, [busy, snapshot]);
  // Retain SDK handle identity through its post-drop focus lookup.
  const dragSurfaceEnabled =
    (reorderableView || projectAssignment) && readableView;
  const canDrag = dragSurfaceEnabled && !busy;
  const canDragRef = useRef(canDrag);
  useLayoutEffect(() => {
    canDragRef.current = canDrag;
  }, [canDrag]);

  usePolling(() => refresh({ showLoading: false }), {
    enabled: active && !disabled && !snapshot && !busy,
  });
  useEffect(() => {
    if (
      !pagination?.clampOffset &&
      !loading &&
      !error &&
      !snapshot &&
      offset > 0 &&
      offset >= total
    ) {
      setOffset(total ? Math.floor((total - 1) / limit) * limit : 0);
    }
  }, [
    loading,
    error,
    snapshot,
    offset,
    total,
    limit,
    setOffset,
    pagination?.clampOffset,
  ]);

  async function finishWrite() {
    if (mounted.current) await latestRefresh.current({ showLoading: false });
    writing.current = false;
    if (mounted.current) {
      setPendingId(null);
      setSavingOrder(false);
      setSnapshot(null);
    }
  }

  function canWrite() {
    return (
      !writing.current &&
      !drag.current &&
      !loading &&
      !error &&
      active &&
      !disabled &&
      !editing
    );
  }

  async function runWrite(
    write: () => Promise<unknown>,
    fallbackMessage: string,
  ) {
    writing.current = true;
    try {
      await write();
    } catch (failure) {
      if (mounted.current)
        notify(
          failure instanceof Error ? failure.message : fallbackMessage,
          'error',
        );
    } finally {
      await finishWrite();
    }
  }

  async function runRowWrite(
    item: ActionItemRow,
    write: () => Promise<unknown>,
    fallbackMessage: string,
  ) {
    if (!canWrite()) return;
    setPendingId(item.id);
    await runWrite(write, fallbackMessage);
  }

  async function runOrderWrite(write: () => Promise<unknown>) {
    if (!canWrite()) return;
    setSavingOrder(true);
    await runWrite(write, 'Could not save this order.');
  }

  function isCurrentOrderItem(item: ActionItemRow) {
    const latest = current.current;
    return (
      mounted.current &&
      item.status === 'open' &&
      latest.orderCurrent &&
      latest.view === view &&
      latest.source === source &&
      latest.items.some(
        (row) =>
          row.id === item.id &&
          row.revision === item.revision &&
          row.priority === item.priority,
      )
    );
  }

  function canMoveToEdge(item: ActionItemRow, edge: 'top' | 'bottom') {
    if (!canWrite() || !orderCurrent || item.status !== 'open') return false;
    const index = items.findIndex(
      (row) => row.id === item.id && row.revision === item.revision,
    );
    if (index === -1) return false;
    return edge === 'top' ? offset + index > 0 : offset + index < total - 1;
  }

  async function moveToEdge(item: ActionItemRow, edge: 'top' | 'bottom') {
    if (!canMoveToEdge(item, edge) || !isCurrentOrderItem(item)) return;
    const focused = document.activeElement;
    orderFocus.current = {
      handle: focused instanceof HTMLButtonElement ? focused : null,
      fallback:
        focused instanceof HTMLElement
          ? (focused.closest<HTMLElement>('.action-items-container') ??
            undefined)
          : undefined,
      view,
    };
    setExpanded(null);
    await runOrderWrite(async () => {
      const boundary = await readItems({
        sort: edge === 'top' ? 'manual' : 'manual_desc',
        limit: 1,
        offset: 0,
      });
      // The source is a snapshot; the move resolves the anchor's live position.
      if (!isCurrentOrderItem(item)) return;
      const anchor = boundary.items[0];
      if (
        !anchor ||
        anchor.status !== 'open' ||
        !Number.isSafeInteger(anchor.id) ||
        anchor.id <= 0
      )
        throw new Error(
          'The list changed. Refresh before moving this item again.',
        );
      if (anchor.id === item.id) return;
      await source.move(item.id, {
        expected_revision: item.revision,
        ...(edge === 'top'
          ? { before_id: anchor.id }
          : { after_id: anchor.id }),
      });
    });
  }

  async function changeStatus(item: ActionItemRow) {
    await runRowWrite(
      item,
      () =>
        source.update(item.id, {
          expected_revision: item.revision,
          status: item.status === 'open' ? 'completed' : 'open',
        }),
      `Could not update this ${noun}.`,
    );
  }

  function canRemove() {
    return (
      Boolean(removeRow) &&
      mounted.current &&
      canWrite() &&
      !criteriaPending &&
      list.dataCurrent &&
      current.current.view === view
    );
  }

  async function removeItem(item: ActionItemRow) {
    const remove = removeRow;
    if (!remove || !canRemove()) return;
    const { id, revision } = item;
    await runRowWrite(
      item,
      () => remove(id, revision),
      `Could not delete this ${noun}.`,
    );
  }

  function startDrag(start?: DragStart) {
    if (!canDragRef.current || writing.current) return;
    const focused = document.activeElement;
    orderFocus.current = {
      handle:
        focused instanceof HTMLButtonElement &&
        focused.classList.contains('action-item-drag')
          ? focused
          : null,
      view: current.current.view,
    };
    const captured = {
      view: current.current.view,
      items: [...current.current.items],
      itemId: start?.draggableId,
      ...(projectAssignment
        ? {
            projects: projectTargets(projectTabsRef.current),
            project: null,
            mode: start?.mode ?? 'FLUID',
          }
        : {}),
    };
    drag.current = captured;
    setSnapshot(captured);
  }

  async function endDrag(result: DropResult) {
    const captured = drag.current;
    drag.current = null;
    if (!captured || !mounted.current) return;
    const sameRows =
      captured.items.length === current.current.items.length &&
      captured.items.every(
        (item, index) =>
          item.id === current.current.items[index].id &&
          item.revision === current.current.items[index].revision &&
          item.priority === current.current.items[index].priority,
      );
    const liveProjects = projectTargets(projectTabsRef.current);
    const sameProjects =
      !captured.projects ||
      (captured.projects.length === liveProjects.length &&
        captured.projects.every(
          (target, index) =>
            target.button === liveProjects[index].button &&
            target.id === liveProjects[index].id &&
            target.name === liveProjects[index].name,
        ));
    if (
      !canDragRef.current ||
      captured.view !== current.current.view ||
      !sameRows ||
      !sameProjects ||
      result.reason === 'CANCEL'
    ) {
      setSnapshot(null);
      if (
        mounted.current &&
        (captured.view !== current.current.view || !sameRows || !sameProjects)
      )
        await latestRefresh.current({ showLoading: false });
      return;
    }
    const item = captured.items[result.source.index];
    if (
      !item ||
      String(item.id) !== result.draggableId ||
      (captured.itemId && captured.itemId !== result.draggableId)
    ) {
      setSnapshot(null);
      return;
    }
    if (captured.project) {
      const target = captured.projects?.find(
        ({ name }) => name === captured.project,
      );
      if (!target || item.project === target.name) {
        setSnapshot(null);
        return;
      }
      if (orderFocus.current) orderFocus.current.fallback = target.button;
      await runRowWrite(
        item,
        () =>
          source.update(item.id, {
            expected_revision: item.revision,
            project: target.name,
          }),
        'Could not move this action item to the project.',
      );
      return;
    }
    if (
      !reorderableView ||
      !result.destination ||
      result.source.droppableId !== result.destination.droppableId ||
      result.source.index === result.destination.index
    ) {
      setSnapshot(null);
      return;
    }
    const reordered = [...captured.items];
    const [moved] = reordered.splice(result.source.index, 1);
    if (
      !moved ||
      String(moved.id) !== result.draggableId ||
      result.destination.index < 0 ||
      result.destination.index >= captured.items.length
    ) {
      setSnapshot(null);
      return;
    }
    reordered.splice(result.destination.index, 0, moved);
    const index = reordered.findIndex((item) => item.id === moved.id);
    const next = reordered[index + 1];
    const anchor: ActionItemMove = next
      ? { expected_revision: moved.revision, before_id: next.id }
      : {
          expected_revision: moved.revision,
          after_id: reordered[index - 1].id,
        };
    setSnapshot({ ...captured, items: reordered });
    await runOrderWrite(async () => {
      try {
        await source.move(moved.id, anchor);
      } catch (failure) {
        if (mounted.current) {
          setItems(captured.items);
          setSnapshot(captured);
        }
        throw failure;
      }
    });
  }

  useLayoutEffect(() => {
    if (!projectAssignment) return;
    function selectProject(project: string | null) {
      if (!drag.current || drag.current.project === project) return;
      drag.current = { ...drag.current, project };
      setSnapshot(drag.current);
    }
    function pointer(x: number, y: number) {
      const captured = drag.current;
      if (captured?.mode !== 'FLUID') return;
      selectProject(
        projectAtPoint(projectTabsRef.current, captured.projects ?? [], x, y),
      );
    }
    const mouse = (event: MouseEvent) => pointer(event.clientX, event.clientY);
    const touch = (event: TouchEvent) => {
      const point = event.changedTouches[0];
      if (point) pointer(point.clientX, point.clientY);
    };
    function keyboard(event: KeyboardEvent) {
      const captured = drag.current;
      if (captured?.mode !== 'SNAP') return;
      if (['ArrowUp', 'ArrowDown', 'Escape'].includes(event.key)) {
        selectProject(null);
        return;
      }
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      const targets = captured.projects ?? [];
      if (!targets.length) return;
      const previous = targets.findIndex(
        ({ name }) => name === captured.project,
      );
      const next =
        previous === -1
          ? event.key === 'ArrowRight'
            ? 0
            : targets.length - 1
          : (previous +
              (event.key === 'ArrowRight' ? 1 : -1) +
              targets.length) %
            targets.length;
      selectProject(targets[next].name);
      targets[next].button.scrollIntoView?.({
        block: 'nearest',
        inline: 'nearest',
      });
    }
    // Register before the SDK installs its active gesture listeners.
    window.addEventListener('mousemove', mouse, {
      capture: true,
      passive: true,
    });
    window.addEventListener('mouseup', mouse, { capture: true, passive: true });
    window.addEventListener('touchmove', touch, {
      capture: true,
      passive: true,
    });
    window.addEventListener('touchend', touch, {
      capture: true,
      passive: true,
    });
    window.addEventListener('keydown', keyboard, true);
    return () => {
      window.removeEventListener('mousemove', mouse, true);
      window.removeEventListener('mouseup', mouse, true);
      window.removeEventListener('touchmove', touch, true);
      window.removeEventListener('touchend', touch, true);
      window.removeEventListener('keydown', keyboard, true);
    };
  }, [projectAssignment]);

  const previousActive = useRef(active);
  useEffect(() => {
    if (active && !previousActive.current && !editing)
      void refresh({ showLoading: false });
    previousActive.current = active;
  }, [active, editing, refresh]);
  return {
    ...list,
    criteriaPending,
    source,
    view,
    busy,
    savingOrder,
    pendingId,
    snapshot,
    expandedId,
    setExpanded,
    reorderableView,
    projectAssignment,
    projectTabsRef,
    dragSurfaceEnabled,
    canDrag,
    startDrag,
    endDrag,
    canMoveToEdge,
    moveToEdge,
    changeStatus,
    deletionEnabled: Boolean(removeRow),
    canRemove,
    removeItem,
    displayed: snapshot?.items ?? items,
    freezeControls: Boolean(snapshot) || savingOrder || editing || disabled,
    canAct: () =>
      !writing.current && !drag.current && active && !disabled && !editing,
  };
}
export type ActionItemQueue = ReturnType<typeof useActionItemQueue>;
