import { Fragment, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { DragDropContext, Draggable, Droppable } from '@hello-pangea/dnd';
import type { ActionItem, ActionItemRow, ActionItemSort } from '../api';
import { ACTION_ITEM_SORT_COLUMNS } from '../constants';
import { columnDirection } from '../utils/tableSorting';
import type { ActionItemQueue } from '../hooks/useActionItemQueue';
import { useApiRead } from '../hooks/useApiRead';
import { DateCell } from './table';
import { SortableHeader, SortButton } from './table/SortableHeader';
import { TableEmptyState } from './ScrollableTable';
import { Pagination } from './Pagination';
import { ActionItemStatusButton } from './ActionItemStatusButton';
import './actionItemQueue.css';

function containProjectCue(cue: HTMLSpanElement | null) {
  if (!cue) return;
  cue.style.left = '0px';
  const rect = cue.getBoundingClientRect();
  const margin = 8;
  const offset = Math.max(
    margin - rect.left,
    Math.min(0, document.documentElement.clientWidth - margin - rect.right),
  );
  cue.style.left = `${offset}px`;
}

function ActionItemDescription({
  item,
  get,
}: {
  item: ActionItemRow;
  get: (id: number) => Promise<ActionItem>;
}) {
  const fetchItem = useCallback(() => get(item.id), [get, item.id]);
  const read = useApiRead(fetchItem);
  return (
    <div
      id={`action-description-${item.id}`}
      className="evidence-detail markdown-content"
      role="region"
      aria-labelledby={`action-title-${item.id}`}
    >
      {read.loading && <p role="status">Loading description…</p>}
      {read.error && (
        <p role="alert">
          {'Could not load this description. '}
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => read.refresh()}
          >
            Retry
          </button>
        </p>
      )}
      {read.data && (
        <ReactMarkdown>
          {read.data.description || 'No description added.'}
        </ReactMarkdown>
      )}
    </div>
  );
}

export function ActionItemQueueTable({
  queue,
  onEdit,
  noun = 'action item',
  plural = 'action items',
  showProject = true,
  showDueDate = false,
  showMoveActions = false,
  scope = 'action-items',
  status,
  sort,
  onSort,
}: {
  queue: ActionItemQueue;
  onEdit: (item: ActionItemRow) => void;
  noun?: string;
  plural?: string;
  showProject?: boolean;
  showDueDate?: boolean;
  showMoveActions?: boolean;
  scope?: string;
  status: string;
  sort: ActionItemSort;
  onSort: (sort: ActionItemSort) => void;
}) {
  const {
    source,
    snapshot,
    loading,
    initialLoading,
    items,
    error,
    refresh,
    savingOrder,
    pendingId,
    setExpanded,
    startDrag,
    endDrag,
    canMoveToEdge,
    moveToEdge,
    canDrag,
    displayed,
    dragSurfaceEnabled,
    reorderableView,
    projectAssignment,
    busy,
    expandedId,
    changeStatus,
    deletionEnabled,
    canRemove,
    removeItem,
    canAct,
    view,
    total,
    limit,
    offset,
    freezeControls,
    setOffset,
    setLimit,
  } = queue;
  const current = queue.dataCurrent && !queue.criteriaPending && !error;
  const sorting = { sort, onSort, current, disabled: freezeControls };
  const columns = ACTION_ITEM_SORT_COLUMNS;
  return (
    <>
      <span className="visually-hidden" role="status" aria-atomic="true">
        {savingOrder
          ? 'Saving order…'
          : pendingId !== null
            ? `Saving ${noun}…`
            : snapshot?.project
              ? `Move ${snapshot.items.find((item) => String(item.id) === snapshot.itemId)?.title ?? 'action item'} to ${snapshot.project}. Press Space to move, or Escape to cancel.`
              : ''}
      </span>
      {!snapshot && initialLoading && (
        <p className="loading">Loading {plural}…</p>
      )}
      {!snapshot && error && (
        <div className="card" role="alert">
          {items.length
            ? `Could not refresh ${plural}. The current list is kept.`
            : `Could not load ${plural}.`}{' '}
          <button className="btn" onClick={() => refresh()}>
            Retry
          </button>
        </div>
      )}
      <>
        <DragDropContext
          dragHandleUsageInstructions={
            projectAssignment
              ? 'Press Space to lift. Use Left and Right to choose a project, Up and Down to reorder in Open Manual view, Space to drop, or Escape to cancel.'
              : undefined
          }
          onBeforeCapture={() => setExpanded(null)}
          onDragStart={startDrag}
          onDragEnd={endDrag}
        >
          {/* Track page scrolling outside the horizontal table viewport. */}
          <Droppable droppableId={scope} isDropDisabled={!canDrag}>
            {(provided) => (
              <div ref={provided.innerRef} {...provided.droppableProps}>
                <div
                  className="table-container action-items-container"
                  style={{ overflowX: 'auto' }}
                  role="region"
                  aria-label={`${plural} list`}
                  tabIndex={0}
                >
                  <table
                    className={`table action-items-table${deletionEnabled ? ' action-items-table-deletable' : ''}`}
                    aria-busy={!current && (loading || !error)}
                  >
                    <colgroup>
                      <col className="action-priority-column" />
                      <col />
                      <col className="action-topics-column" />
                      <col className="action-updated-column" />
                      <col className="action-controls-column" />
                    </colgroup>
                    <thead>
                      <tr>
                        {status === 'open' ? (
                          <SortableHeader
                            {...sorting}
                            column={columns.priority}
                            title="Ascending Priority enables drag ordering"
                          >
                            Priority
                          </SortableHeader>
                        ) : (
                          <th scope="col">Priority</th>
                        )}
                        <SortableHeader {...sorting} column={columns.title}>
                          Title
                        </SortableHeader>
                        {showProject ? (
                          <th
                            scope="col"
                            aria-sort={
                              current
                                ? (columnDirection(sort, columns.project) ??
                                  columnDirection(sort, columns.tags))
                                : undefined
                            }
                          >
                            <div className="action-project-tag-sorts">
                              <SortButton {...sorting} column={columns.project}>
                                Project
                              </SortButton>
                              <span aria-hidden="true">/</span>
                              <SortButton {...sorting} column={columns.tags}>
                                Tags
                              </SortButton>
                            </div>
                          </th>
                        ) : (
                          <SortableHeader {...sorting} column={columns.tags}>
                            Tags
                          </SortableHeader>
                        )}
                        <SortableHeader
                          {...sorting}
                          column={showDueDate ? columns.due : columns.updated}
                        >
                          {showDueDate ? 'Due date' : 'Updated'}
                        </SortableHeader>
                        <th scope="col">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayed.map((item, index) => (
                        <Draggable
                          key={item.id}
                          draggableId={String(item.id)}
                          index={index}
                          isDragDisabled={!dragSurfaceEnabled}
                          disableInteractiveElementBlocking
                        >
                          {(row, state) => (
                            <Fragment>
                              <tr
                                ref={row.innerRef}
                                {...row.draggableProps}
                                className="action-item-row"
                                aria-busy={pendingId === item.id}
                                style={{
                                  ...row.draggableProps.style,
                                  display: state.isDragging
                                    ? 'table'
                                    : undefined,
                                  tableLayout: state.isDragging
                                    ? 'fixed'
                                    : undefined,
                                  background: state.isDragging
                                    ? 'var(--surface-hover)'
                                    : undefined,
                                }}
                              >
                                <td>
                                  {state.isDragging && snapshot?.project && (
                                    <span
                                      ref={(cue) => containProjectCue(cue)}
                                      className="tag tag-project action-item-project-drop-cue"
                                      aria-hidden="true"
                                      title={`Move to ${snapshot.project}`}
                                    >
                                      → {snapshot.project}
                                    </span>
                                  )}
                                  <div className="flex-row">
                                    {(reorderableView || projectAssignment) && (
                                      <button
                                        type="button"
                                        className="btn btn-sm action-item-drag"
                                        {...row.dragHandleProps}
                                        disabled={!canDrag}
                                        aria-label={
                                          reorderableView
                                            ? `Reorder ${item.title}`
                                            : `Move ${item.title} to project`
                                        }
                                        title={
                                          projectAssignment
                                            ? 'Drag onto a project; press Space, then Left or Right to choose a project'
                                            : 'Drag to reorder; press Space to use the keyboard'
                                        }
                                      >
                                        ⠿
                                      </button>
                                    )}
                                    <span
                                      className="action-item-priority"
                                      aria-label={
                                        savingOrder
                                          ? 'Priority updating'
                                          : item.priority === null
                                            ? 'No open queue priority'
                                            : `Priority ${item.priority}`
                                      }
                                    >
                                      {savingOrder
                                        ? '…'
                                        : (item.priority ?? '—')}
                                    </span>
                                  </div>
                                </td>
                                <td>
                                  <button
                                    type="button"
                                    id={`action-title-${item.id}`}
                                    className="inline-clear action-item-title"
                                    aria-label={item.title}
                                    aria-expanded={expandedId === item.id}
                                    aria-controls={`action-description-${item.id}`}
                                    disabled={busy || freezeControls}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      if (canAct())
                                        setExpanded(
                                          expandedId === item.id
                                            ? null
                                            : { id: item.id, view },
                                        );
                                    }}
                                  >
                                    <span aria-hidden="true">
                                      {expandedId === item.id ? '⌄' : '›'}
                                    </span>
                                    {item.title}
                                  </button>
                                </td>
                                <td>
                                  {showProject && item.project && (
                                    <span className="tag tag-project">
                                      {item.project}
                                    </span>
                                  )}
                                  {item.tags.map((tag) => (
                                    <span className="tag" key={tag}>
                                      {tag}
                                    </span>
                                  ))}
                                </td>
                                <td>
                                  {showDueDate ? (
                                    item.due_at ? (
                                      <DateCell
                                        date={item.due_at}
                                        format="long"
                                      />
                                    ) : (
                                      'No due date'
                                    )
                                  ) : (
                                    <DateCell date={item.updated_at} />
                                  )}
                                </td>
                                <td>
                                  <div className="flex-row action-item-actions">
                                    {showMoveActions &&
                                      reorderableView &&
                                      (['top', 'bottom'] as const).map(
                                        (edge) => (
                                          <button
                                            key={edge}
                                            type="button"
                                            className="btn btn-sm"
                                            aria-label={`Move ${item.title} to ${edge}`}
                                            title={`Move to ${edge} of the matching action items`}
                                            disabled={
                                              !canMoveToEdge(item, edge)
                                            }
                                            onKeyDown={(event) =>
                                              event.stopPropagation()
                                            }
                                            onClick={(event) => {
                                              event.stopPropagation();
                                              void moveToEdge(item, edge);
                                            }}
                                          >
                                            Move to {edge}
                                          </button>
                                        ),
                                      )}
                                    <ActionItemStatusButton
                                      noun={noun}
                                      item={item}
                                      small
                                      disabled={
                                        busy ||
                                        freezeControls ||
                                        loading ||
                                        Boolean(error)
                                      }
                                      onChange={() => {
                                        void changeStatus(item);
                                      }}
                                    />
                                    <button
                                      type="button"
                                      className="btn btn-sm"
                                      aria-label={`Edit ${item.title}`}
                                      disabled={busy || freezeControls}
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        if (canAct()) onEdit(item);
                                      }}
                                    >
                                      Edit
                                    </button>
                                    {deletionEnabled && (
                                      <button
                                        type="button"
                                        className="btn btn-sm btn-danger"
                                        aria-label={`Delete ${item.title}`}
                                        disabled={!canRemove()}
                                        onKeyDown={(event) =>
                                          event.stopPropagation()
                                        }
                                        onClick={(event) => {
                                          event.stopPropagation();
                                          if (
                                            canRemove() &&
                                            confirm(
                                              `Delete ${noun} “${item.title}”?`,
                                            )
                                          )
                                            void removeItem(item);
                                        }}
                                      >
                                        Delete
                                      </button>
                                    )}
                                  </div>
                                </td>
                              </tr>
                              {expandedId === item.id && (
                                <tr className="evidence-row-expanded">
                                  <td colSpan={5}>
                                    <ActionItemDescription
                                      get={source.get}
                                      key={`${item.id}:${item.revision}`}
                                      item={item}
                                    />
                                  </td>
                                </tr>
                              )}
                            </Fragment>
                          )}
                        </Draggable>
                      ))}
                      {provided.placeholder}
                    </tbody>
                  </table>
                  <TableEmptyState>
                    {displayed.length === 0 && current && !loading ? (
                      <p className="loading" role="status">
                        No {status === 'all' ? '' : `${status} `}
                        {plural} found.
                      </p>
                    ) : undefined}
                  </TableEmptyState>
                </div>
              </div>
            )}
          </Droppable>
        </DragDropContext>
        <Pagination
          total={total}
          limit={limit}
          offset={offset}
          disabled={freezeControls}
          onPageChange={setOffset}
          onLimitChange={(value) => {
            setLimit(value);
            setOffset(0);
          }}
        />
      </>
    </>
  );
}
