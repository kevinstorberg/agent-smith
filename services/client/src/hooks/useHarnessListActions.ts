import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { DropResult } from '@hello-pangea/dnd';
import { api, type HarnessItem, type HarnessMove } from '../api';
import { useNotification } from '../context/useNotification';

interface Snapshot { type: string; view: string; items: HarnessItem[] }
type Metadata = Partial<Pick<HarnessItem, 'enabled' | 'clone_as_skill'>>;

function unchangedRows(left: HarnessItem[], right: HarnessItem[]): boolean {
  return left.length === right.length && left.every((item, index) => {
    const other = right[index];
    return item.id === other.id && item.version === other.version
      && item.updated_at === other.updated_at && item.sort_key === other.sort_key;
  });
}

export function useHarnessListActions({ type, view, items, readable, manual, refresh, setItems }: {
  type: string; view: string; items: HarnessItem[]; readable: boolean; manual: boolean;
  refresh: (options: { showLoading: boolean }) => Promise<void>;
  setItems: Dispatch<SetStateAction<HarnessItem[]>>;
}) {
  const { notify } = useNotification();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [operation, setOperation] = useState<'order' | 'metadata' | null>(null);
  const drag = useRef<Snapshot | null>(null);
  const writing = useRef(false);
  const mounted = useRef(false);
  const focusedHandle = useRef<HTMLButtonElement | null>(null);
  const current = useRef({ type, view, items, readable, manual, refresh });
  useLayoutEffect(() => {
    current.current = { type, view, items, readable, manual, refresh };
    if (drag.current && drag.current.view !== view) {
      drag.current = null;
      setSnapshot(null);
    }
  }, [type, view, items, readable, manual, refresh]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const busy = operation !== null;
  const captured = snapshot?.view === view ? snapshot : null;
  const canDrag = manual && readable && items.length > 1 && !busy;

  useEffect(() => {
    if (busy || captured) return;
    const handle = focusedHandle.current;
    focusedHandle.current = null;
    if (handle?.isConnected && !handle.disabled && document.activeElement === document.body) handle.focus({ preventScroll: true });
  }, [busy, captured]);

  async function write(capture: Snapshot, kind: 'order' | 'metadata', action: () => Promise<unknown>) {
    writing.current = true;
    setOperation(kind);
    try {
      await action();
    } catch {
      if (mounted.current && current.current.type === capture.type) {
        if (kind === 'order' && current.current.view === capture.view) setSnapshot(capture);
        notify(kind === 'order' ? 'Could not save this order. Refresh and try again.' : 'Could not update item. Please try again.', 'error');
      }
    } finally {
      try {
        if (mounted.current && current.current.type === capture.type) {
          // Keep rollback rows underneath the drag preview until a canonical read succeeds.
          if (kind === 'order' && current.current.view === capture.view) setItems(capture.items);
          await current.current.refresh({ showLoading: false });
        }
      } finally {
        writing.current = false;
        if (mounted.current) { setOperation(null); setSnapshot(null); }
      }
    }
  }

  function startDrag() {
    const live = current.current;
    if (!mounted.current || live.type !== type || live.view !== view || !live.readable || !live.manual
      || live.items.length < 2 || writing.current || drag.current) return;
    const active = document.activeElement;
    focusedHandle.current = active instanceof HTMLButtonElement && active.classList.contains('harness-drag-handle') ? active : null;
    const capture = { type: live.type, view: live.view, items: [...live.items] };
    drag.current = capture;
    setSnapshot(capture);
  }

  async function endDrag(result: DropResult) {
    const capture = drag.current;
    if (!capture || capture.type !== type || capture.view !== view) return;
    drag.current = null;
    const live = current.current;
    const destination = result.destination?.index;
    const source = result.source.index;
    if (!mounted.current || writing.current || !live.readable || !live.manual || capture.view !== live.view
      || !unchangedRows(capture.items, live.items) || result.reason !== 'DROP'
      || destination === undefined || !Number.isInteger(source) || !Number.isInteger(destination)
      || source < 0 || source >= capture.items.length || destination < 0 || destination >= capture.items.length
      || source === destination || String(capture.items[source].id) !== result.draggableId) {
      setSnapshot(null);
      return;
    }
    const reordered = [...capture.items];
    const [moved] = reordered.splice(source, 1);
    reordered.splice(destination, 0, moved);
    const next = reordered[destination + 1];
    const anchor = next ?? reordered[destination - 1];
    const body: HarnessMove = {
      expected_updated_at: moved.updated_at, expected_anchor_updated_at: anchor.updated_at,
      ...(next ? { before_id: anchor.id } : { after_id: anchor.id }),
    };
    setSnapshot({ ...capture, items: reordered });
    setItems(reordered);
    await write(capture, 'order', () => api.harness.items.move(capture.type, moved.id, body));
  }

  async function updateMetadata(item: HarnessItem, metadata: Metadata) {
    const live = current.current;
    if (!mounted.current || live.type !== type || live.view !== view || !live.readable || writing.current || drag.current
      || !live.items.some(row => row.id === item.id && row.version === item.version && row.updated_at === item.updated_at)) return;
    await write({ type: live.type, view: live.view, items: [...live.items] }, 'metadata',
      () => api.harness.items.updateMetadata(live.type, item.id, metadata));
  }

  return { displayed: captured?.items ?? items, canDrag, busy, savingOrder: operation === 'order',
    freezeControls: Boolean(captured) || busy, startDrag, endDrag, updateMetadata };
}
