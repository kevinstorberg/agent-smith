import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { DragDropContext, Droppable, Draggable, type DropResult } from '@hello-pangea/dnd';
import { api } from '../api';
import type { HarnessItem } from '../api';
import { Pagination } from '../components/Pagination';
import { usePagination } from '../hooks/usePagination';
import { useNotification } from '../context/useNotification';

const TYPE_LABELS: Record<string, string> = {
  rule: 'Rules',
  skill: 'Skills',
  tool: 'Tools',
  hook: 'Hooks',
};

export function HarnessIndexPage({ type }: { type: string }) {
  const [nameInput, setNameInput] = useState('');
  const [projectInput, setProjectInput] = useState('');
  const [nameFilter, setNameFilter] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const navigate = useNavigate();
  const { notify } = useNotification();

  const hasFilters = !!(nameFilter || projectFilter);

  const { items, setItems, total, loading, limit, offset, setLimit, setOffset } = usePagination<HarnessItem>(
    (l, o) => api.harness.items.list(type, {
      limit: l, offset: o,
      name: nameFilter || undefined,
      project: projectFilter || undefined,
    }),
    [type, nameFilter, projectFilter],
  );

  const dragDisabled = hasFilters;

  // Debounce name and project inputs
  useEffect(() => {
    const timeout = setTimeout(() => setNameFilter(nameInput), 300);
    return () => clearTimeout(timeout);
  }, [nameInput]);

  useEffect(() => {
    const timeout = setTimeout(() => setProjectFilter(projectInput), 300);
    return () => clearTimeout(timeout);
  }, [projectInput]);

  useEffect(() => {
    setNameInput('');
    setProjectInput('');
    setNameFilter('');
    setProjectFilter('');
  }, [type]);

  const toggleEnabled = async (item: HarnessItem) => {
    await api.harness.items.updateMetadata(type, item.id, { enabled: !item.enabled });
    setItems(prev => prev.map(i => i.id === item.id ? { ...i, enabled: !i.enabled } : i));
  };

  const toggleCloneAsSkill = async (item: HarnessItem) => {
    await api.harness.items.updateMetadata(type, item.id, { clone_as_skill: !item.clone_as_skill });
    setItems(prev => prev.map(i => i.id === item.id ? { ...i, clone_as_skill: !i.clone_as_skill } : i));
  };

  const onDragEnd = async (result: DropResult) => {
    if (!result.destination || result.source.index === result.destination.index) return;

    const reordered = [...items];
    const [moved] = reordered.splice(result.source.index, 1);
    reordered.splice(result.destination.index, 0, moved);
    setItems(reordered);

    try {
      await api.harness.items.reorder(type, reordered.map(i => i.id));
      notify('Sort order saved', 'success');
    } catch {
      notify('Failed to save order', 'error');
    }
  };

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div>
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>{TYPE_LABELS[type] || type}</h2>
        </div>
        <button className="btn btn-primary" onClick={() => navigate(`/harness/${type}/new`)}>
          + New {type.charAt(0).toUpperCase() + type.slice(1)}
        </button>
      </div>

      <div className="filters" style={{ marginBottom: 12 }}>
        <input
          placeholder="Search by name..."
          value={nameInput}
          onChange={e => setNameInput(e.target.value)}
          style={{ maxWidth: 260 }}
        />
        <input
          placeholder="Filter by project..."
          value={projectInput}
          onChange={e => setProjectInput(e.target.value)}
          style={{ maxWidth: 220 }}
        />
      </div>

      <DragDropContext onDragEnd={onDragEnd}>
        <Droppable droppableId="harness-table" isDropDisabled={dragDisabled}>
          {(provided) => (
            <table className="table">
              <thead>
                <tr>
                  {!dragDisabled && <th style={{ width: 36 }}></th>}
                  <th>Name</th>
                  <th>Project</th>
                  <th>Enabled</th>
                  {type === 'rule' && <th>Skill Clone</th>}
                  <th>Agents</th>
                  <th>Configs</th>
                  <th>Version</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody ref={provided.innerRef} {...provided.droppableProps}>
                {items.map((item, index) => (
                  <Draggable key={String(item.id)} draggableId={String(item.id)} index={index} isDragDisabled={dragDisabled}>
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
                        {!dragDisabled && (
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
                        {type === 'rule' && (
                          <td onClick={e => e.stopPropagation()}>
                            <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
                              <input
                                type="checkbox"
                                checked={!!item.clone_as_skill}
                                onChange={() => toggleCloneAsSkill(item)}
                                style={{ accentColor: 'var(--highlight)', width: 16, height: 16 }}
                              />
                              <span style={{ color: item.clone_as_skill ? 'var(--highlight)' : 'var(--text-muted)', fontSize: 12 }}>
                                {item.clone_as_skill ? 'On' : 'Off'}
                              </span>
                            </label>
                          </td>
                        )}
                        <td>
                          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                            {item.agents.map(a => (
                              <span key={a} className="tag">{a}</span>
                            ))}
                          </div>
                        </td>
                        <td>
                          {(item.configs ?? []).length > 0 ? (
                            <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
                              <span className="tag" style={{ fontSize: 11 }}>{item.configs.length}</span>
                              {item.configs.some(c => c.device !== '*') && (
                                <span className="tag" style={{ background: 'rgba(255,165,0,0.15)', color: 'var(--warning)', fontSize: 10 }}>device</span>
                              )}
                              {item.configs.some(c => c.repo !== '*') && (
                                <span className="tag" style={{ background: 'rgba(100,200,100,0.15)', color: 'var(--success)', fontSize: 10 }}>repo</span>
                              )}
                            </div>
                          ) : (
                            <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>default</span>
                          )}
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
                {items.length === 0 && (
                  <tr><td colSpan={(dragDisabled ? 7 : 8) + (type === 'rule' ? 1 : 0)} className="loading">No {TYPE_LABELS[type]?.toLowerCase() || 'items'} found</td></tr>
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
