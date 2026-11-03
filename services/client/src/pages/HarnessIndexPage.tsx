import type { CSSProperties } from 'react';
import { useNavigate } from 'react-router';
import { DragDropContext, Droppable, Draggable } from '@hello-pangea/dnd';
import { api } from '../api';
import type { HarnessItem } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { ProjectCell, EnabledToggleCell, BadgeCell, DateCell, VersionCell } from '../components/table';
import { usePagination } from '../hooks/usePagination';
import { makeKeyboardClickable } from '../utils/a11y';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { HARNESS_SORT_OPTIONS } from '../constants';
import { harnessViewKey, parseViewField } from '../utils/viewPreferences';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { useHarnessListActions } from '../hooks/useHarnessListActions';

const TYPE_LABELS: Record<string, string> = {
  rule: 'Rules',
  skill: 'Skills',
  tool: 'Tools',
  hook: 'Hooks',
  agent: 'Agents',
};

export function HarnessIndexPage({ type }: { type: string }) {
  const preferenceKey = harnessViewKey(type);
  const preferences = useViewPreferences(preferenceKey);
  const { name: nameInput, project: projectInput, sort } = preferences.values;
  const nameFilter = useDebouncedValue(nameInput);
  const projectFilter = useDebouncedValue(projectInput);
  const navigate = useNavigate();

  const criteriaPending = nameFilter !== nameInput || projectFilter !== projectInput;

  const { items, setItems, total, loading, error, dataCurrent, refresh, limit, offset, setLimit, setOffset } = usePagination<HarnessItem>(
    (l, o) => api.harness.items.list(type, {
      limit: l, offset: o,
      name: nameFilter || undefined,
      project: projectFilter || undefined,
      sort,
    }),
    [type, nameFilter, projectFilter, sort],
    10, { ...preferences.pagination, enabled: !criteriaPending },
  );

  const manual = sort === 'manual';
  const readable = !criteriaPending && dataCurrent && !loading && !error;
  const view = JSON.stringify([type, nameInput, projectInput, nameFilter, projectFilter, sort, limit, offset]);
  const actions = useHarnessListActions({ type, view, items, readable, manual, refresh, setItems });
  const columns = [manual && '32px', 'minmax(220px, 2fr)', 'minmax(120px, 1fr)', '72px',
    type === 'rule' && '88px', 'minmax(160px, 1fr)', '90px', '64px', '144px'].filter(Boolean).join(' ');

  return (
    <div>
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 className="page-title">{TYPE_LABELS[type] || type}</h2>
        </div>
        <button className="btn btn-primary" disabled={actions.freezeControls} onClick={() => navigate(`/harness/${type}/new`)}>
          + New {type.charAt(0).toUpperCase() + type.slice(1)}
        </button>
      </div>

      <FilterBar
        nameValue={nameInput}
        projectValue={projectInput}
        onNameChange={value => preferences.setField('name', value)}
        onProjectChange={value => preferences.setField('project', value)}
        onReset={preferences.reset}
        disabled={actions.freezeControls}
      >
        <label><span className="form-label">Sort</span>
          <select className="input" disabled={actions.freezeControls} value={sort} onChange={event => { if (!actions.freezeControls) preferences.setField('sort', parseViewField(preferenceKey, 'sort', event.target.value)); }}>
            {HARNESS_SORT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
      </FilterBar>
      {loading && items.length === 0 && <div className="loading">Loading...</div>}
      {!loading && error && <div role="alert" className="card">
        Could not load {TYPE_LABELS[type]?.toLowerCase() || 'items'}. <button className="btn" onClick={() => refresh()}>Retry</button>
      </div>}
      {items.length > 0 && !readable && <p role="status">Showing previous results. Reordering is unavailable until this view loads.</p>}
      <span role="status" className="visually-hidden">{actions.savingOrder ? 'Saving order…' : actions.busy ? 'Updating item…' : ''}</span>

      {(items.length > 0 || (!loading && !error)) && <>
      <DragDropContext onBeforeDragStart={actions.startDrag} onDragEnd={actions.endDrag}>
        <Droppable droppableId="harness-table" isDropDisabled={!actions.canDrag}>
          {(provided) => (
            <div className="table-container" style={{ '--harness-columns': columns } as CSSProperties}>
              <div className="harness-list-scroll" role="region" aria-label={`${TYPE_LABELS[type] || type} list`} tabIndex={0}>
              <div className="harness-list-table">
              <div className="table-header harness-list-header">
                {manual && <div></div>}
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
                {actions.displayed.map((item, index) => (
                  <Draggable key={String(item.id)} draggableId={String(item.id)} index={index} isDragDisabled={!manual} disableInteractiveElementBlocking>
                    {(prov, snapshot) => (
                      <div
                        className="harness-list-row"
                        ref={prov.innerRef}
                        {...prov.draggableProps}
                        {...makeKeyboardClickable(() => navigate(`/harness/${type}/${item.id}`))}
                        style={{
                          background: snapshot.isDragging ? 'var(--surface-hover)' : undefined,
                          ...prov.draggableProps.style,
                        }}
                        onMouseEnter={e => { if (!snapshot.isDragging) e.currentTarget.style.background = 'var(--surface-hover)'; }}
                        onMouseLeave={e => { if (!snapshot.isDragging) e.currentTarget.style.background = ''; }}
                      >
                        {manual && (
                          <button
                            {...prov.dragHandleProps}
                            type="button"
                            className="harness-drag-handle"
                            aria-label={`Reorder ${item.name}`}
                            disabled={!actions.canDrag}
                            onClick={e => e.stopPropagation()}
                            style={{ cursor: actions.canDrag ? 'grab' : 'default', color: 'var(--text-muted)', fontSize: 16,
                              textAlign: 'center', background: 'transparent', border: 0, padding: 0,
                              pointerEvents: actions.canDrag ? undefined : 'none' }}
                          >
                            ⠿
                          </button>
                        )}
                        <div>{item.name}</div>
                        <ProjectCell project={item.project} />
                        <EnabledToggleCell
                          enabled={item.enabled}
                          disabled={!readable || actions.freezeControls}
                          onChange={() => actions.updateMetadata(item, { enabled: !item.enabled })}
                          ariaLabel={`Enable ${item.name}`}
                        />
                        {type === 'rule' && (
                          <EnabledToggleCell
                            enabled={!!item.clone_as_skill}
                            disabled={!readable || actions.freezeControls}
                            onChange={() => actions.updateMetadata(item, { clone_as_skill: !item.clone_as_skill })}
                            ariaLabel={`Clone ${item.name} as a skill`}
                            accentColor="var(--highlight)"
                          />
                        )}
                        <BadgeCell items={item.agents} />
                        <div>
                          {(item.configs ?? []).length > 0 ? (
                            <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
                              <span className="tag tag-sm">{item.configs.length}</span>
                              {item.configs.some(c => c.device !== '*') && (
                                <span className="tag tag-warning">device</span>
                              )}
                              {item.configs.some(c => c.repo !== '*') && (
                                <span className="tag tag-success">repo</span>
                              )}
                            </div>
                          ) : (
                            <span className="text-muted-sm">default</span>
                          )}
                        </div>
                        <VersionCell version={item.version} />
                        <DateCell date={item.updated_at} />
                      </div>
                    )}
                  </Draggable>
                ))}
                {provided.placeholder}
              </div>
              </div>
              </div>
              {!loading && items.length === 0 && <div className="loading">No {TYPE_LABELS[type]?.toLowerCase() || 'items'} found</div>}
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
        disabled={actions.freezeControls || !readable}
      />
      </>}
    </div>
  );
}
