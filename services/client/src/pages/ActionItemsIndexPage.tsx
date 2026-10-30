import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import ReactMarkdown from 'react-markdown';
import { DragDropContext, Draggable, Droppable, type DropResult } from '@hello-pangea/dnd';
import { api } from '../api';
import type { ActionItemFilters, ActionItemMove, ActionItemRow, ActionItemSort } from '../api';
import { DateCell } from '../components/table';
import { Pagination } from '../components/Pagination';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { useNotification } from '../context/useNotification';
import { useApiRead } from '../hooks/useApiRead';
import { actionItemTags } from '../utils/actionItems';
import { ActionItemStatusButton } from '../components/ActionItemStatusButton';

const TABS = [['open', 'Open'], ['completed', 'Completed'], ['all', 'All']] as const;
type Status = NonNullable<ActionItemFilters['status']>;
interface DragSnapshot { items: ActionItemRow[]; view: string }

function ActionItemDescription({ item }: { item: ActionItemRow }) {
  const fetchItem = useCallback(() => api.actionItems.get(item.id), [item.id]);
  const read = useApiRead(fetchItem);
  return <div id={`action-description-${item.id}`} className="evidence-detail markdown-content" role="region" aria-labelledby={`action-title-${item.id}`}>
    {read.loading && <p role="status">Loading description…</p>}
    {read.error && <p role="alert">Could not load this description. <button type="button" className="btn btn-sm" onClick={() => read.refresh()}>Retry</button></p>}
    {read.data && <ReactMarkdown>{read.data.description || 'No description added.'}</ReactMarkdown>}
  </div>;
}

export function ActionItemsIndexPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<Status>('open');
  const [sort, setSort] = useState<ActionItemSort>('manual');
  const [queryInput, setQueryInput] = useState('');
  const [projectInput, setProjectInput] = useState('');
  const [tagsInput, setTagsInput] = useState('');
  const query = useDebouncedValue(queryInput.trim());
  const project = useDebouncedValue(projectInput.trim());
  const tags = useDebouncedValue(tagsInput.trim());
  const [snapshot, setSnapshot] = useState<DragSnapshot | null>(null);
  const drag = useRef<DragSnapshot | null>(null);
  const dragFocus = useRef<HTMLButtonElement | null>(null);
  const [savingOrder, setSavingOrder] = useState(false);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const writing = useRef(false);
  const { notify } = useNotification();
  const list = usePagination<ActionItemRow>((limit, offset) => api.actionItems.list({
    limit, offset, status, sort, q: query || undefined, project: project || undefined,
    tags: actionItemTags(tags),
  }), [status, sort, query, project, tags]);
  const { items, total, loading, error, limit, offset, setOffset, setLimit, refresh, setItems } = list;
  const latestRefresh = useRef(refresh);
  const mounted = useRef(false);
  useEffect(() => { latestRefresh.current = refresh; }, [refresh]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const view = JSON.stringify([status, sort, queryInput, projectInput, tagsInput, limit, offset]);
  const [expanded, setExpanded] = useState<{ id: number; view: string } | null>(null);
  const expandedId = expanded?.view === view ? expanded.id : null;
  useEffect(() => { if (expanded && expanded.view !== view) setExpanded(null); }, [expanded, view]);
  const current = useRef({ view, items });
  useEffect(() => { current.current = { view, items }; });
  const busy = savingOrder || pendingId !== null;
  useEffect(() => {
    if (busy || snapshot) return;
    const handle = dragFocus.current;
    dragFocus.current = null;
    if (handle?.isConnected && !handle.disabled && document.activeElement === document.body) handle.focus({ preventScroll: true });
  }, [busy, snapshot]);
  const filtered = Boolean(queryInput.trim() || projectInput.trim() || tagsInput.trim() || query || project || tags);
  const reorderableView = status === 'open' && sort === 'manual' && !filtered;
  // Retain SDK handle identity through its post-drop focus lookup.
  const dragSurfaceEnabled = reorderableView && !loading && !error;
  const canDrag = dragSurfaceEnabled && !busy;
  const canDragRef = useRef(canDrag);
  useEffect(() => { canDragRef.current = canDrag; }, [canDrag]);

  usePolling(() => refresh({ showLoading: false }), { enabled: !snapshot && !busy });
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
    if (writing.current || drag.current || loading || error) return;
    writing.current = true;
    setPendingId(item.id);
    try {
      await api.actionItems.update(item.id, {
        expected_revision: item.revision, status: item.status === 'open' ? 'completed' : 'open',
      });
    } catch (failure) {
      notify(failure instanceof Error ? failure.message : 'Could not update this action item.', 'error');
    } finally {
      await finishWrite();
    }
  }

  function editItem(item: ActionItemRow) {
    if (!writing.current && !drag.current) navigate(`/action-items/${item.id}?edit=1`);
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
      await api.actionItems.move(moved.id, anchor);
    } catch (failure) {
      setItems(captured.items);
      setSnapshot(captured);
      notify(failure instanceof Error ? failure.message : 'Could not save this order.', 'error');
    } finally {
      await finishWrite();
    }
  }

  const displayed = snapshot?.items ?? items;
  const freezeControls = Boolean(snapshot) || savingOrder;
  return <div>
    <div className="page-header"><h2 className="page-title">Action items</h2>
      <Link className="btn btn-primary" style={{ textDecoration: 'none' }} to="/action-items/new">New action item</Link>
    </div>
    <div className="sub-tabs" role="tablist" aria-label="Action item status">
      {TABS.map(([value, label]) => <button key={value} role="tab" aria-selected={status === value}
        className={status === value ? 'active' : ''} disabled={freezeControls} onClick={() => {
          setStatus(value); setSort(value === 'open' ? 'manual' : value === 'completed' ? 'completed' : 'newest');
        }}>{label}</button>)}
    </div>
    <div className="profile-filters">
      <label><span className="form-label">Search action items</span><input className="input" type="search" maxLength={1000}
        value={queryInput} disabled={freezeControls} onChange={event => setQueryInput(event.target.value)} placeholder="Search title or description…" /></label>
      <label><span className="form-label">Project</span><input className="input" maxLength={200} value={projectInput}
        disabled={freezeControls} onChange={event => setProjectInput(event.target.value)} placeholder="All projects" /></label>
      <label><span className="form-label">Tags</span><input className="input" value={tagsInput} disabled={freezeControls}
        onChange={event => setTagsInput(event.target.value)} placeholder="Tags, comma-separated" /></label>
      <label><span className="form-label">Sort</span><select className="input" value={sort} disabled={freezeControls}
        onChange={event => setSort(event.target.value as ActionItemSort)}>
        {status === 'open' && <option value="manual">Manual order</option>}
        {status === 'completed' && <option value="completed">Recently completed</option>}
        <option value="newest">Newest</option><option value="updated">Recently updated</option><option value="title">Title A–Z</option>
      </select></label>
    </div>
    {(filtered || status !== 'open' || sort !== 'manual') && <p className="text-muted-sm">To drag items into order, use Open with Manual order and clear the filters.</p>}
    <span className="visually-hidden" role="status">{savingOrder ? 'Saving order…' : pendingId !== null ? 'Saving action item…' : ''}</span>
    {!snapshot && loading && !items.length && <p className="loading">Loading action items…</p>}
    {!snapshot && error && <div className="card" role="alert">{items.length ? 'Could not refresh action items. The current list is kept.' : 'Could not load action items.'} <button className="btn" onClick={() => refresh({ showLoading: false })}>Retry</button></div>}
    {(snapshot || items.length > 0 || (!loading && !error)) && <>
      <DragDropContext onBeforeCapture={() => setExpanded(null)} onDragStart={startDrag} onDragEnd={endDrag}>
        {/* Track page scrolling outside the horizontal table viewport. */}
        <Droppable droppableId="action-items" isDropDisabled={!canDrag}>
          {provided => <div ref={provided.innerRef} {...provided.droppableProps}>
            <div className="table-container action-items-container" style={{ overflowX: 'auto' }}>
              <table className="table action-items-table">
                <colgroup><col className="action-priority-column" /><col /><col className="action-topics-column" /><col className="action-updated-column" /><col className="action-controls-column" /></colgroup>
                <thead><tr><th>Priority</th><th>Title</th><th>Project / tags</th><th>Updated</th><th>Actions</th></tr></thead>
                <tbody>
                  {displayed.map((item, index) => <Draggable key={item.id} draggableId={String(item.id)} index={index} isDragDisabled={!dragSurfaceEnabled} disableInteractiveElementBlocking>
                    {(row, state) => <Fragment><tr ref={row.innerRef} {...row.draggableProps} className="action-item-row" aria-busy={pendingId === item.id}
                      style={{ ...row.draggableProps.style, display: state.isDragging ? 'table' : undefined, tableLayout: state.isDragging ? 'fixed' : undefined, background: state.isDragging ? 'var(--surface-hover)' : undefined }}>
                      <td><div className="flex-row">{reorderableView && <button type="button" className="btn btn-sm action-item-drag" {...row.dragHandleProps} disabled={!canDrag}
                        aria-label={`Reorder ${item.title}`} title="Drag to reorder; press Space to use the keyboard">⠿</button>}
                        <span className="action-item-priority" aria-label={item.priority === null ? 'No open queue priority' : `Priority ${item.priority}`}>{item.priority ?? '—'}</span>
                      </div></td>
                      <td><button type="button" id={`action-title-${item.id}`} className="inline-clear action-item-title" aria-label={item.title}
                        aria-expanded={expandedId === item.id} aria-controls={`action-description-${item.id}`} disabled={busy || Boolean(snapshot)}
                        onClick={event => { event.stopPropagation(); if (!writing.current && !drag.current) setExpanded(expandedId === item.id ? null : { id: item.id, view }); }}>
                        <span aria-hidden="true">{expandedId === item.id ? '⌄' : '›'}</span>{item.title}
                      </button></td>
                      <td>{item.project && <span className="tag tag-project">{item.project}</span>}
                        {item.tags.map(tag => <span className="tag" key={tag}>{tag}</span>)}</td>
                      <td><DateCell date={item.updated_at} /></td>
                      <td><div className="flex-row">
                        <ActionItemStatusButton item={item} small disabled={busy || Boolean(snapshot) || loading || Boolean(error)} onChange={() => { void changeStatus(item); }} />
                        <button type="button" className="btn btn-sm" aria-label={`Edit ${item.title}`}
                          disabled={busy || Boolean(snapshot)} onClick={event => { event.stopPropagation(); editItem(item); }}>Edit</button>
                      </div></td>
                    </tr>{expandedId === item.id && <tr className="evidence-row-expanded"><td colSpan={5}><ActionItemDescription key={`${item.id}:${item.revision}`} item={item} /></td></tr>}</Fragment>}
                  </Draggable>)}
                  {displayed.length === 0 && <tr><td colSpan={5} className="loading">No {status === 'all' ? '' : `${status} `}action items found.</td></tr>}
                  {provided.placeholder}
                </tbody>
              </table>
            </div>
          </div>}
        </Droppable>
      </DragDropContext>
      <Pagination total={total} limit={limit} offset={offset} disabled={freezeControls}
        onPageChange={setOffset} onLimitChange={value => { setLimit(value); setOffset(0); }} />
    </>}
  </div>;
}
