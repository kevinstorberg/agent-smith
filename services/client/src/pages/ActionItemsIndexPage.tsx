import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { DragDropContext, Draggable, Droppable, type DropResult } from '@hello-pangea/dnd';
import { api } from '../api';
import type { ActionItemFilters, ActionItemMove, ActionItemRow, ActionItemSort } from '../api';
import { DateCell } from '../components/table';
import { Pagination } from '../components/Pagination';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { useNotification } from '../context/useNotification';
import { actionItemTags } from '../utils/actionItems';

const TABS = [['open', 'Open'], ['completed', 'Completed'], ['all', 'All']] as const;
type Status = NonNullable<ActionItemFilters['status']>;
interface DragSnapshot { items: ActionItemRow[]; view: string }

export function ActionItemsIndexPage() {
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
  const current = useRef({ view, items });
  useEffect(() => { current.current = { view, items }; });
  const busy = savingOrder || pendingId !== null;
  const filtered = Boolean(queryInput.trim() || projectInput.trim() || tagsInput.trim() || query || project || tags);
  const canDrag = status === 'open' && sort === 'manual' && !filtered && !loading && !error && !busy;
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
    if (writing.current || drag.current) return;
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

  function startDrag() {
    if (!canDragRef.current || writing.current) return;
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
        && item.revision === current.current.items[index].revision);
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
    writing.current = true;
    setSavingOrder(true);
    setSnapshot({ ...captured, items: reordered });
    setItems(reordered);
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
    {savingOrder && <p role="status">Saving order…</p>}
    {!snapshot && loading && <p className="loading">Loading action items…</p>}
    {!snapshot && error && <div className="card" role="alert">Could not load action items. <button className="btn" onClick={() => refresh()}>Retry</button></div>}
    {(snapshot || (!loading && !error)) && <>
      <DragDropContext onDragStart={startDrag} onDragEnd={endDrag}>
        <div className="table-container" style={{ overflowX: 'auto' }}>
          <table className="table action-items-table">
            <thead><tr><th aria-label="Reorder" /><th>Complete</th><th>Title</th><th>Project / tags</th><th>Updated</th></tr></thead>
            <Droppable droppableId="action-items" isDropDisabled={!canDrag}>
              {provided => <tbody ref={provided.innerRef} {...provided.droppableProps}>
                {displayed.map((item, index) => <Draggable key={item.id} draggableId={String(item.id)} index={index} isDragDisabled={!canDrag} disableInteractiveElementBlocking>
                  {(row, state) => <tr ref={row.innerRef} {...row.draggableProps} aria-busy={pendingId === item.id}
                    style={{ ...row.draggableProps.style, background: state.isDragging ? 'var(--surface-hover)' : undefined }}>
                    <td>{canDrag && <button type="button" className="btn btn-sm action-item-drag" {...row.dragHandleProps}
                      aria-label={`Reorder ${item.title}`} title="Drag to reorder; press Space to use the keyboard">⠿</button>}</td>
                    <td><input className="form-checkbox" type="checkbox" checked={item.status === 'completed'}
                      aria-label={`${item.status === 'completed' ? 'Reopen' : 'Complete'} ${item.title}`}
                      disabled={busy || Boolean(snapshot)} onChange={() => changeStatus(item)} />
                      {pendingId === item.id && <span className="text-muted-sm" role="status">Saving…</span>}</td>
                    <td><Link className="text-link" to={`/action-items/${item.id}`}>{item.title}</Link></td>
                    <td>{item.project && <span className="tag tag-project">{item.project}</span>}
                      {item.tags.map(tag => <span className="tag" key={tag}>{tag}</span>)}</td>
                    <td><DateCell date={item.updated_at} /></td>
                  </tr>}
                </Draggable>)}
                {displayed.length === 0 && <tr><td colSpan={5} className="loading">No {status === 'all' ? '' : `${status} `}action items found.</td></tr>}
                {provided.placeholder}
              </tbody>}
            </Droppable>
          </table>
        </div>
      </DragDropContext>
      <Pagination total={total} limit={limit} offset={offset} disabled={freezeControls}
        onPageChange={setOffset} onLimitChange={value => { setLimit(value); setOffset(0); }} />
    </>}
  </div>;
}
