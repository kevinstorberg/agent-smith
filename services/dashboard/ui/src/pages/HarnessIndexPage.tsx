import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { DragDropContext, Droppable, Draggable, type DropResult } from '@hello-pangea/dnd';
import { api } from '../api';
import type { HarnessItem } from '../api';
import { Pagination } from '../components/Pagination';
import { usePagination } from '../hooks/usePagination';

const TYPE_LABELS: Record<string, string> = {
  rule: 'Rules',
  skill: 'Skills',
  tool: 'Tools',
  hook: 'Hooks',
};

export function HarnessIndexPage({ type }: { type: string }) {
  const [projectFilter, setProjectFilter] = useState('');
  const [nameFilter, setNameFilter] = useState('');
  const [saveMsg, setSaveMsg] = useState('');
  const navigate = useNavigate();

  const hasFilters = !!(nameFilter || projectFilter);

  const { items, setItems, total, loading, limit, offset, setLimit, setOffset } = usePagination<HarnessItem>(
    (l, o) => api.harness.items.list(type, { limit: l, offset: o }),
    [type],
  );

  useEffect(() => {
    setOffset(0);
    setNameFilter('');
    setProjectFilter('');
  }, [type]);

  const toggleEnabled = async (item: HarnessItem) => {
    await api.harness.items.updateMetadata(type, item.id, { enabled: !item.enabled });
    setItems(prev => prev.map(i => i.id === item.id ? { ...i, enabled: !i.enabled } : i));
  };

  const onDragEnd = async (result: DropResult) => {
    if (!result.destination || result.source.index === result.destination.index) return;

    const reordered = [...items];
    const [moved] = reordered.splice(result.source.index, 1);
    reordered.splice(result.destination.index, 0, moved);
    setItems(reordered);

    try {
      await api.harness.items.reorder(type, reordered.map(i => i.id));
      setSaveMsg('Sort order saved');
      setTimeout(() => setSaveMsg(''), 2000);
    } catch {
      setSaveMsg('Failed to save order');
      setTimeout(() => setSaveMsg(''), 3000);
    }
  };

  const displayed = items.filter(i => {
    if (nameFilter && !i.name.toLowerCase().includes(nameFilter.toLowerCase())) return false;
    if (projectFilter) {
      const pf = projectFilter.toLowerCase();
      if (!(i.project?.toLowerCase().includes(pf) || (!i.project && pf === 'shared'))) return false;
    }
    return true;
  });

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div>
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>{TYPE_LABELS[type] || type}</h2>
          {saveMsg && (
            <span style={{ fontSize: 12, color: 'var(--success)', transition: 'opacity 0.3s' }}>
              {saveMsg}
            </span>
          )}
        </div>
        <button className="btn btn-primary" onClick={() => navigate(`/harness/${type}/new`)}>
          + New {type.charAt(0).toUpperCase() + type.slice(1)}
        </button>
      </div>

      <div className="filters" style={{ marginBottom: 12 }}>
        <input
          placeholder="Search by name..."
          value={nameFilter}
          onChange={e => setNameFilter(e.target.value)}
          style={{ maxWidth: 260 }}
        />
        <input
          placeholder="Filter by project..."
          value={projectFilter}
          onChange={e => setProjectFilter(e.target.value)}
          style={{ maxWidth: 220 }}
        />
      </div>

      <DragDropContext onDragEnd={onDragEnd}>
        <Droppable droppableId="harness-table" isDropDisabled={hasFilters}>
          {(provided) => (
            <table className="table">
              <thead>
                <tr>
                  {!hasFilters && <th style={{ width: 36 }}></th>}
                  <th>Name</th>
                  <th>Project</th>
                  <th>Enabled</th>
                  <th>Agents</th>
                  <th>Version</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody ref={provided.innerRef} {...provided.droppableProps}>
                {displayed.map((item, index) => (
                  <Draggable key={String(item.id)} draggableId={String(item.id)} index={index} isDragDisabled={hasFilters}>
                    {(prov, snapshot) => (
                      <tr
                        ref={prov.innerRef}
                        {...prov.draggableProps}
                        onClick={() => navigate(`/harness/${type}/${item.id}`)}
                        style={{
                          cursor: 'pointer',
                          background: snapshot.isDragging ? 'var(--surface-hover)' : undefined,
                          ...prov.draggableProps.style,
                        }}
                      >
                        {!hasFilters && (
                          <td
                            {...prov.dragHandleProps}
                            onClick={e => e.stopPropagation()}
                            style={{ cursor: 'grab', color: 'var(--text-muted)', fontSize: 16, textAlign: 'center', padding: '8px 4px' }}
                          >
                            ⠿
                          </td>
                        )}
                        <td>{item.name}</td>
                        <td>
                          {item.project
                            ? <span className="tag tag-project">{item.project}</span>
                            : <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>shared</span>
                          }
                        </td>
                        <td onClick={e => e.stopPropagation()}>
                          <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
                            <input
                              type="checkbox"
                              checked={item.enabled}
                              onChange={() => toggleEnabled(item)}
                              style={{ accentColor: 'var(--success)', width: 16, height: 16 }}
                            />
                            <span style={{ color: item.enabled ? 'var(--success)' : 'var(--text-muted)', fontSize: 12 }}>
                              {item.enabled ? 'On' : 'Off'}
                            </span>
                          </label>
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                            {item.agents.map(a => (
                              <span key={a} className="tag">{a}</span>
                            ))}
                          </div>
                        </td>
                        <td style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>v{item.version}</td>
                        <td style={{ color: 'var(--text-muted)', fontSize: 13 }}>
                          {new Date(item.updated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                        </td>
                      </tr>
                    )}
                  </Draggable>
                ))}
                {provided.placeholder}
                {displayed.length === 0 && (
                  <tr><td colSpan={hasFilters ? 6 : 7} className="loading">No {TYPE_LABELS[type]?.toLowerCase() || 'items'} found</td></tr>
                )}
              </tbody>
            </table>
          )}
        </Droppable>
      </DragDropContext>

      <Pagination
        total={total}
        limit={limit}
        offset={offset}
        onPageChange={setOffset}
        onLimitChange={newLimit => { setLimit(newLimit); setOffset(0); }}
      />
    </div>
  );
}
