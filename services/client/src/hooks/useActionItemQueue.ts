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
  const dragFocus = useRef<{
    handle: HTMLButtonElement | null;
    fallback?: HTMLButtonElement;
    view: string;
  } | null>(null);
  const projectTabsRef = useRef<HTMLDivElement>(null);
  const [savingOrder, setSavingOrder] = useState(false);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const writing = useRef(false);
  const { notify } = useNotification();
  const list = usePagination<ActionItemRow>(
    (limit, offset) => source.list({ ...filters, limit, offset }),
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
  const current = useRef({ view, items });
  useLayoutEffect(() => {
    current.current = { view, items };
  });
  const busy = savingOrder || pendingId !== null || editing;
  useEffect(() => {
    if (busy || snapshot) return;
    const focus = dragFocus.current;
    dragFocus.current = null;
    const handle = focus?.handle?.isConnected
      ? focus.handle
      : focus?.view === current.current.view
        ? focus?.fallback
        : null;
    if (
      handle?.isConnected &&
      !handle.disabled &&
      document.activeElement === document.body
    )
      handle.focus({ preventScroll: true });
  }, [busy, snapshot]);
  // Retain SDK handle identity through its post-drop focus lookup.
  const dragSurfaceEnabled =
    (reorderableView || projectAssignment) &&
    !criteriaPending &&
    list.dataCurrent &&
    !loading &&
    !error &&
    active &&
    !disabled &&
    !editing;
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

  async function runRowWrite(
    item: ActionItemRow,
    write: () => Promise<unknown>,
    fallbackMessage: string,
  ) {
    if (!canWrite()) return;
    writing.current = true;
    setPendingId(item.id);
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
    dragFocus.current = {
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
      if (dragFocus.current) dragFocus.current.fallback = target.button;
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
    writing.current = true;
    setSavingOrder(true);
    setSnapshot({ ...captured, items: reordered });
    try {
      await source.move(moved.id, anchor);
    } catch (failure) {
      if (!mounted.current) return;
      setItems(captured.items);
      setSnapshot(captured);
      notify(
        failure instanceof Error
          ? failure.message
          : 'Could not save this order.',
        'error',
      );
    } finally {
      await finishWrite();
    }
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
