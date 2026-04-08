import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { DragDropContext, Droppable, Draggable, type DropResult } from '@hello-pangea/dnd';
import { api } from '../api';
import type { HarnessItem } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { ProjectCell, EnabledToggleCell, BadgeCell, DateCell, VersionCell } from '../components/table';
import { usePagination } from '../hooks/usePagination';
import { useNotification } from '../context/useNotification';
import { makeKeyboardClickable } from '../utils/a11y';

const TYPE_LABELS: Record<string, string> = {
  rule: 'Rules',
  skill: 'Skills',
  tool: 'Tools',
  hook: 'Hooks',
  agent: 'Agents',
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

      <FilterBar
        nameValue={nameInput}
        projectValue={projectInput}
        onNameChange={setNameInput}
        onProjectChange={setProjectInput}
      />

      <DragDropContext onDragEnd={onDragEnd}>
        <Droppable droppableId="harness-table" isDropDisabled={dragDisabled}>
          {(provided) => (
            <div className="table-container">
              <div className="table-header" style={{
                display: 'grid',
                gridTemplateColumns: dragDisabled
                  ? (type === 'rule' ? '1fr 0.8fr 0.6fr 0.6fr 1fr 0.6fr 0.5fr 1fr' : '1fr 0.8fr 0.6fr 1fr 0.6fr 0.5fr 1fr')
                  : (type === 'rule' ? '36px 1fr 0.8fr 0.6fr 0.6fr 1fr 0.6fr 0.5fr 1fr' : '36px 1fr 0.8fr 0.6fr 1fr 0.6fr 0.5fr 1fr'),
                gap: '8px',
                padding: '12px 16px',
                background: 'var(--surface)',
                borderBottom: '1px solid var(--border)',
                fontSize: '12px',
                fontWeight: 600,
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}>
                {!dragDisabled && <div></div>}
                <div>Name</div>
                <div>Project</div>
                <div>Enabled</div>
                {type === 'rule' && <div>Skill Clone</div>}
                <div>Agents</div>
                <div>Configs</div>
                <div>Version</div>
                <div>Updated</div>
              </div>
              <div ref={provided.innerRef} {...provided.droppableProps}>
                {items.map((item, index) => (
                  <Draggable key={String(item.id)} draggableId={String(item.id)} index={index} isDragDisabled={dragDisabled}>
                    {(prov, snapshot) => (
                      <div
                        ref={prov.innerRef}
                        {...prov.draggableProps}
                        {...makeKeyboardClickable(() => navigate(`/harness/${type}/${item.id}`))}
                        style={{
                          display: 'grid',
                          gridTemplateColumns: dragDisabled
                            ? (type === 'rule' ? '1fr 0.8fr 0.6fr 0.6fr 1fr 0.6fr 0.5fr 1fr' : '1fr 0.8fr 0.6fr 1fr 0.6fr 0.5fr 1fr')
                            : (type === 'rule' ? '36px 1fr 0.8fr 0.6fr 0.6fr 1fr 0.6fr 0.5fr 1fr' : '36px 1fr 0.8fr 0.6fr 1fr 0.6fr 0.5fr 1fr'),
                          gap: '8px',
                          padding: '12px 16px',
                          alignItems: 'center',
                          cursor: 'pointer',
                          background: snapshot.isDragging ? 'var(--surface-hover)' : undefined,
                          borderBottom: '1px solid var(--border)',
                          transition: 'background var(--transition)',
                          ...prov.draggableProps.style,
                        }}
                        onMouseEnter={e => { if (!snapshot.isDragging) e.currentTarget.style.background = 'var(--surface-hover)'; }}
                        onMouseLeave={e => { if (!snapshot.isDragging) e.currentTarget.style.background = ''; }}
                      >
                        {!dragDisabled && (
                          <div
                            {...prov.dragHandleProps}
                            onClick={e => e.stopPropagation()}
                            style={{ cursor: 'grab', color: 'var(--text-muted)', fontSize: 16, textAlign: 'center' }}
                          >
                            ⠿
                          </div>
                        )}
                        <div>{item.name}</div>
                        <ProjectCell project={item.project} />
                        <EnabledToggleCell
                          enabled={item.enabled}
                          onChange={() => toggleEnabled(item)}
                        />
                        {type === 'rule' && (
                          <EnabledToggleCell
                            enabled={!!item.clone_as_skill}
                            onChange={() => toggleCloneAsSkill(item)}
                            accentColor="var(--highlight)"
                          />
                        )}
                        <BadgeCell items={item.agents} />
                        <div>
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
                        </div>
                        <VersionCell version={item.version} />
                        <DateCell date={item.updated_at} />
                      </div>
                    )}
                  </Draggable>
                ))}
                {items.length === 0 && (
                  <div className="loading" style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '48px 24px' }}>
                    No {TYPE_LABELS[type]?.toLowerCase() || 'items'} found
                  </div>
                )}
                {provided.placeholder}
              </div>
            </div>
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
