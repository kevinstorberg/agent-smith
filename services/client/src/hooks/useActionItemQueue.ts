import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { DropResult } from '@hello-pangea/dnd';
import type { ActionItem, ActionItemFilters, ActionItemMove, ActionItemPatch, ActionItemRow, Paginated } from '../api';
import { usePagination } from './usePagination';
import { usePolling } from './usePolling';
import { useNotification } from '../context/useNotification';

export interface ActionItemQueueSource {
  list: (filters: ActionItemFilters) => Promise<Paginated<ActionItemRow>>;
  get: (id: number) => Promise<ActionItem>;
  update: (id: number, body: ActionItemPatch) => Promise<ActionItem>;
  move: (id: number, body: ActionItemMove) => Promise<ActionItem>;
}
interface DragSnapshot { items: ActionItemRow[]; view: string }

export function useActionItemQueue({ source, filters, criteria, viewKey, reorderableView, active = true, disabled = false, editing = false, noun = 'action item' }: {
  source: ActionItemQueueSource; filters: ActionItemFilters; criteria: string; viewKey: string; reorderableView: boolean;
  active?: boolean; disabled?: boolean; editing?: boolean; noun?: string;
}) {
  const [snapshot, setSnapshot] = useState<DragSnapshot | null>(null);
  const drag = useRef<DragSnapshot | null>(null);
  const dragFocus = useRef<HTMLButtonElement | null>(null);
  const [savingOrder, setSavingOrder] = useState(false);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const writing = useRef(false);
  const { notify } = useNotification();
  const list = usePagination<ActionItemRow>((limit, offset) => source.list({ ...filters, limit, offset }), [criteria]);
  const { items, total, loading, error, limit, offset, setOffset, refresh, setItems } = list;
  const latestRefresh = useRef(refresh);
  const mounted = useRef(false);
  useLayoutEffect(() => { latestRefresh.current = refresh; }, [refresh]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const view = JSON.stringify([viewKey, limit, offset]);
  const [expanded, setExpanded] = useState<{ id: number; view: string } | null>(null);
  const expandedId = expanded?.view === view ? expanded.id : null;
  useEffect(() => { if (expanded && expanded.view !== view) setExpanded(null); }, [expanded, view]);
  const current = useRef({ view, items });
  useLayoutEffect(() => { current.current = { view, items }; });
  const busy = savingOrder || pendingId !== null || editing;
  useEffect(() => {
    if (busy || snapshot) return;
    const handle = dragFocus.current;
    dragFocus.current = null;
    if (handle?.isConnected && !handle.disabled && document.activeElement === document.body) handle.focus({ preventScroll: true });
  }, [busy, snapshot]);
  // Retain SDK handle identity through its post-drop focus lookup.
  const dragSurfaceEnabled = reorderableView && !loading && !error && active && !disabled && !editing;
  const canDrag = dragSurfaceEnabled && !busy;
  const canDragRef = useRef(canDrag);
  useLayoutEffect(() => { canDragRef.current = canDrag; }, [canDrag]);

  usePolling(() => refresh({ showLoading: false }), { enabled: active && !disabled && !snapshot && !busy });
  useEffect(() => {
    if (!loading && !error && !snapshot && offset > 0 && offset >= total) {
      setOffset(total ? Math.floor((total - 1) / limit) * limit : 0);
    }
  }, [loading, error, snapshot, offset, total, limit, setOffset]);

  async function finishWrite() {
    if (mounted.current) await latestRefresh.current({ showLoading: false });
    writing.current = false;
    if (mounted.current) { setPendingId(null); setSavingOrder(false); setSnapshot(null); }
  }

  async function changeStatus(item: ActionItemRow) {
    if (writing.current || drag.current || loading || error || !active || disabled || editing) return;
    writing.current = true;
    setPendingId(item.id);
    try {
      await source.update(item.id, {
        expected_revision: item.revision, status: item.status === 'open' ? 'completed' : 'open',
      });
    } catch (failure) {
      if (mounted.current) notify(failure instanceof Error ? failure.message : `Could not update this ${noun}.`, 'error');
    } finally {
      await finishWrite();
    }
  }

  function startDrag() {
    if (!canDragRef.current || writing.current) return;
    const focused = document.activeElement;
    dragFocus.current = focused instanceof HTMLButtonElement && focused.classList.contains('action-item-drag') ? focused : null;
    const captured = { view: current.current.view, items: [...current.current.items] };
    drag.current = captured;
    setSnapshot(captured);
  }

  async function endDrag(result: DropResult) {
    const captured = drag.current;
    drag.current = null;
    if (!captured) return;
    const sameRows = captured.items.length === current.current.items.length
      && captured.items.every((item, index) => item.id === current.current.items[index].id
        && item.revision === current.current.items[index].revision && item.priority === current.current.items[index].priority);
    if (!canDragRef.current || captured.view !== current.current.view || !sameRows
      || !result.destination || result.source.index === result.destination.index) {
      setSnapshot(null);
      if (captured.view !== current.current.view || !sameRows) await refresh({ showLoading: false });
      return;
    }
    const reordered = [...captured.items];
    const [moved] = reordered.splice(result.source.index, 1);
    if (!moved || String(moved.id) !== result.draggableId
      || result.destination.index < 0 || result.destination.index >= captured.items.length) {
      setSnapshot(null);
      return;
    }
    reordered.splice(result.destination.index, 0, moved);
    const index = reordered.findIndex(item => item.id === moved.id);
    const next = reordered[index + 1];
    const anchor: ActionItemMove = next
      ? { expected_revision: moved.revision, before_id: next.id }
      : { expected_revision: moved.revision, after_id: reordered[index - 1].id };
    const optimistic = reordered.map((item, position) => ({ ...item, priority: captured.items[position].priority }));
    writing.current = true;
    setSavingOrder(true);
    setSnapshot({ ...captured, items: optimistic });
    setItems(optimistic);
    try {
      await source.move(moved.id, anchor);
    } catch (failure) {
      if (!mounted.current) return;
      setItems(captured.items);
      setSnapshot(captured);
      notify(failure instanceof Error ? failure.message : 'Could not save this order.', 'error');
    } finally {
      await finishWrite();
    }
  }

  const previousActive = useRef(active);
  useEffect(() => {
    if (active && !previousActive.current && !editing) void refresh({ showLoading: false });
    previousActive.current = active;
  }, [active, editing, refresh]);
  return { ...list, source, view, busy, savingOrder, pendingId, snapshot, expandedId, setExpanded, reorderableView,
    dragSurfaceEnabled, canDrag, startDrag, endDrag, changeStatus,
    displayed: snapshot?.items ?? items, freezeControls: Boolean(snapshot) || savingOrder || editing || disabled,
    canAct: () => !writing.current && !drag.current && active && !disabled && !editing };
}
export type ActionItemQueue = ReturnType<typeof useActionItemQueue>;
