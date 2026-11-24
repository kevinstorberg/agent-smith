import { Fragment } from 'react';
import { DragDropContext, Draggable, Droppable } from '@hello-pangea/dnd';
import type { ActionItemRow, ActionItemSort } from '../api';
import type { ActionItemQueue } from '../hooks/useActionItemQueue';
import { TableEmptyState } from './ScrollableTable';
import { Pagination } from './Pagination';
import {
  ActionItemDescription,
  ActionItemQueueCells,
} from './ActionItemQueueRow';
import { ActionItemQueueHead } from './ActionItemQueueHead';
import './actionItemQueue.css';

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
    canDrag,
    displayed,
    dragSurfaceEnabled,
    projectAssignment,
    expandedId,
    deletionEnabled,
    total,
    limit,
    offset,
    freezeControls,
    setOffset,
    setLimit,
  } = queue;
  const current = queue.dataCurrent && !queue.criteriaPending && !error;
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
                    <ActionItemQueueHead
                      sort={sort}
                      onSort={onSort}
                      current={current}
                      disabled={freezeControls}
                      status={status}
                      showProject={showProject}
                      showDueDate={showDueDate}
                    />
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
                                <ActionItemQueueCells
                                  item={item}
                                  row={row}
                                  state={state}
                                  queue={queue}
                                  onEdit={onEdit}
                                  noun={noun}
                                  showProject={showProject}
                                  showDueDate={showDueDate}
                                  showMoveActions={showMoveActions}
                                />
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
