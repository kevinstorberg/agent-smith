import type { CSSProperties } from 'react';
import { useNavigate } from 'react-router';
import { DragDropContext, Droppable, Draggable } from '@hello-pangea/dnd';
import { api } from '../api';
import type { HarnessItem } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import {
  ProjectCell,
  EnabledToggleCell,
  BadgeCell,
  DateCell,
  VersionCell,
} from '../components/table';
import { SortableHeader } from '../components/table/SortableHeader';
import { usePagination } from '../hooks/usePagination';
import { makeKeyboardClickable } from '../utils/a11y';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { HARNESS_SORT_COLUMNS } from '../constants';
import { harnessViewKey } from '../utils/viewPreferences';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { useHarnessListActions } from '../hooks/useHarnessListActions';
import { usePolling } from '../hooks/usePolling';
import './harnessSorting.css';

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

  const criteriaPending =
    nameFilter !== nameInput || projectFilter !== projectInput;

  const {
    items,
    setItems,
    total,
    loading,
    initialLoading,
    error,
    dataCurrent,
    refresh,
    limit,
    offset,
    setLimit,
    setOffset,
  } = usePagination<HarnessItem>(
    (l, o) =>
      api.harness.items.list(type, {
        limit: l,
        offset: o,
        name: nameFilter || undefined,
        project: projectFilter || undefined,
        sort,
      }),
    [type, nameFilter, projectFilter, sort],
    10,
    { ...preferences.pagination, enabled: !criteriaPending },
  );

  const manual = sort === 'manual';
  const readable = !criteriaPending && dataCurrent && !loading && !error;
  const view = JSON.stringify([
    type,
    nameInput,
    projectInput,
    nameFilter,
    projectFilter,
    sort,
    limit,
    offset,
  ]);
  const actions = useHarnessListActions({
    type,
    view,
    items,
    readable,
    manual,
    refresh,
    setItems,
  });
  usePolling(() => refresh({ showLoading: false }), {
    enabled: !loading && !criteriaPending && !actions.freezeControls,
  });
  const columns: {
    key: keyof typeof HARNESS_SORT_COLUMNS;
    label: string;
    minimum: number;
    grow?: number;
  }[] = [
    { key: 'order', label: 'Order', minimum: 6 },
    { key: 'name', label: 'Name', minimum: 13, grow: 2 },
    { key: 'project', label: 'Project', minimum: 9, grow: 1 },
    { key: 'enabled', label: 'Enabled', minimum: 7 },
    ...(type === 'rule'
      ? [{ key: 'clone_as_skill' as const, label: 'Skill Clone', minimum: 8 }]
      : []),
    { key: 'agents', label: 'Agents', minimum: 10, grow: 1 },
    { key: 'configs', label: 'Configs', minimum: 6.5 },
    { key: 'version', label: 'Version', minimum: 6.5 },
    { key: 'updated', label: 'Updated', minimum: 9 },
  ];
  const gridColumns = columns
    .map((column) =>
      column.grow
        ? `minmax(${column.minimum}em, ${column.grow}fr)`
        : `${column.minimum}em`,
    )
    .join(' ');
  const minimumWidth = `calc(${columns.reduce((sum, column) => sum + column.minimum, 0)}em + ${columns.length - 1} * var(--harness-sort-gap) + 2 * var(--harness-sort-padding))`;

  return (
    <div>
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 className="page-title">{TYPE_LABELS[type] || type}</h2>
        </div>
        <button
          className="btn btn-primary"
          disabled={actions.freezeControls}
          onClick={() => navigate(`/harness/${type}/new`)}
        >
          + New {type.charAt(0).toUpperCase() + type.slice(1)}
        </button>
      </div>

      <FilterBar
        nameValue={nameInput}
        projectValue={projectInput}
        onNameChange={(value) => preferences.setField('name', value)}
        onProjectChange={(value) => preferences.setField('project', value)}
        disabled={actions.freezeControls}
      />
      {initialLoading && <div className="loading">Loading...</div>}
      {!loading && error && (
        <div role="alert" className="card">
          Could not load {TYPE_LABELS[type]?.toLowerCase() || 'items'}
          {'. '}
          <button className="btn" onClick={() => refresh()}>
            Retry
          </button>
        </div>
      )}
      <span role="status" className="visually-hidden">
        {actions.savingOrder
          ? 'Saving order…'
          : actions.busy
            ? 'Updating item…'
            : ''}
      </span>

      <>
        <DragDropContext
          onBeforeDragStart={actions.startDrag}
          onDragEnd={actions.endDrag}
        >
          <Droppable
            droppableId="harness-table"
            isDropDisabled={!actions.canDrag}
          >
            {(provided) => (
              <div
                className="table-container harness-sorting-container"
                style={
                  {
                    '--harness-columns': gridColumns,
                    '--harness-minimum-width': minimumWidth,
                  } as CSSProperties
                }
              >
                <div
                  className="harness-list-scroll"
                  role="region"
                  aria-label={`${TYPE_LABELS[type] || type} list`}
                  tabIndex={0}
                >
                  <div
                    className="harness-list-table"
                    role="table"
                    aria-label={`${TYPE_LABELS[type] || type} items`}
                    aria-busy={
                      (!dataCurrent ||
                        criteriaPending ||
                        loading ||
                        actions.busy) &&
                      !error
                    }
                  >
                    <div role="rowgroup">
                      <div
                        className="table-header harness-list-header"
                        role="row"
                      >
                        {columns.map((column) => (
                          <SortableHeader
                            key={column.key}
                            as="div"
                            sort={sort}
                            column={HARNESS_SORT_COLUMNS[column.key]}
                            current={readable && !actions.freezeControls}
                            disabled={actions.freezeControls}
                            onSort={(value) => {
                              if (!actions.freezeControls)
                                preferences.setField('sort', value);
                            }}
                          >
                            {column.label}
                          </SortableHeader>
                        ))}
                      </div>
                    </div>
                    <div
                      role="rowgroup"
                      ref={provided.innerRef}
                      {...provided.droppableProps}
                    >
                      {actions.displayed.map((item, index) => (
                        <Draggable
                          key={String(item.id)}
                          draggableId={String(item.id)}
                          index={index}
                          isDragDisabled={!manual}
                          disableInteractiveElementBlocking
                        >
                          {(prov, snapshot) => (
                            <div
                              className="harness-list-row"
                              ref={prov.innerRef}
                              {...prov.draggableProps}
                              {...makeKeyboardClickable(() =>
                                navigate(`/harness/${type}/${item.id}`),
                              )}
                              role="row"
                              style={{
                                background: snapshot.isDragging
                                  ? 'var(--surface-hover)'
                                  : undefined,
                                ...prov.draggableProps.style,
                              }}
                              onMouseEnter={(e) => {
                                if (!snapshot.isDragging)
                                  e.currentTarget.style.background =
                                    'var(--surface-hover)';
                              }}
                              onMouseLeave={(e) => {
                                if (!snapshot.isDragging)
                                  e.currentTarget.style.background = '';
                              }}
                            >
                              <div
                                role="cell"
                                className="harness-sort-order-cell"
                              >
                                <button
                                  {...prov.dragHandleProps}
                                  type="button"
                                  className="harness-drag-handle"
                                  aria-label={`Reorder ${item.name}`}
                                  disabled={!actions.canDrag}
                                  onClick={(e) => e.stopPropagation()}
                                  style={{
                                    cursor: actions.canDrag
                                      ? 'grab'
                                      : 'default',
                                    color: 'var(--text-muted)',
                                    fontSize: 16,
                                    textAlign: 'center',
                                    background: 'transparent',
                                    border: 0,
                                    padding: 0,
                                    pointerEvents: actions.canDrag
                                      ? undefined
                                      : 'none',
                                  }}
                                >
                                  ⠿
                                </button>
                              </div>
                              <div role="cell">{item.name}</div>
                              <div role="cell">
                                <ProjectCell project={item.project} />
                              </div>
                              <div role="cell">
                                <EnabledToggleCell
                                  enabled={item.enabled}
                                  disabled={!readable || actions.freezeControls}
                                  onChange={() =>
                                    actions.updateMetadata(item, {
                                      enabled: !item.enabled,
                                    })
                                  }
                                  ariaLabel={`Enable ${item.name}`}
                                />
                              </div>
                              {type === 'rule' && (
                                <div role="cell">
                                  <EnabledToggleCell
                                    enabled={!!item.clone_as_skill}
                                    disabled={
                                      !readable || actions.freezeControls
                                    }
                                    onChange={() =>
                                      actions.updateMetadata(item, {
                                        clone_as_skill: !item.clone_as_skill,
                                      })
                                    }
                                    ariaLabel={`Clone ${item.name} as a skill`}
                                    accentColor="var(--highlight)"
                                  />
                                </div>
                              )}
                              <div role="cell">
                                <BadgeCell items={item.agents} />
                              </div>
                              <div role="cell">
                                {(item.configs ?? []).length > 0 ? (
                                  <div
                                    style={{
                                      display: 'flex',
                                      gap: 4,
                                      alignItems: 'center',
                                      flexWrap: 'wrap',
                                    }}
                                  >
                                    <span className="tag tag-sm">
                                      {item.configs.length}
                                    </span>
                                    {item.configs.some(
                                      (c) => c.device !== '*',
                                    ) && (
                                      <span className="tag tag-warning">
                                        device
                                      </span>
                                    )}
                                    {item.configs.some(
                                      (c) => c.repo !== '*',
                                    ) && (
                                      <span className="tag tag-success">
                                        repo
                                      </span>
                                    )}
                                  </div>
                                ) : (
                                  <span className="text-muted-sm">default</span>
                                )}
                              </div>
                              <div role="cell">
                                <VersionCell version={item.version} />
                              </div>
                              <div role="cell">
                                <DateCell date={item.updated_at} />
                              </div>
                            </div>
                          )}
                        </Draggable>
                      ))}
                      {provided.placeholder}
                    </div>
                  </div>
                </div>
                {!loading && items.length === 0 && (
                  <div className="loading">
                    No {TYPE_LABELS[type]?.toLowerCase() || 'items'} found
                  </div>
                )}
              </div>
            )}
          </Droppable>
        </DragDropContext>

        <Pagination
          total={total}
          limit={limit}
          offset={offset}
          onPageChange={setOffset}
          onLimitChange={(newLimit) => {
            setLimit(newLimit);
            setOffset(0);
          }}
          disabled={actions.freezeControls || !readable}
        />
      </>
    </div>
  );
}
