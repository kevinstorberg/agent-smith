import { Fragment, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { DragDropContext, Draggable, Droppable } from '@hello-pangea/dnd';
import type { ActionItem, ActionItemRow } from '../api';
import type { ActionItemQueue } from '../hooks/useActionItemQueue';
import { useApiRead } from '../hooks/useApiRead';
import { DateCell } from './table';
import { Pagination } from './Pagination';
import { ActionItemStatusButton } from './ActionItemStatusButton';
import './actionItemQueue.css';

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
  scope = 'action-items',
  status,
}: {
  queue: ActionItemQueue;
  onEdit: (item: ActionItemRow) => void;
  noun?: string;
  plural?: string;
  showProject?: boolean;
  scope?: string;
  status: string;
}) {
  const {
    source,
    snapshot,
    loading,
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
    reorderableView,
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
  return (
    <>
      <span className="visually-hidden" role="status">
        {savingOrder
          ? 'Saving order…'
          : pendingId !== null
            ? `Saving ${noun}…`
            : ''}
      </span>
      {!snapshot && loading && !items.length && (
        <p className="loading">Loading {plural}…</p>
      )}
      {!snapshot && error && (
        <div className="card" role="alert">
          {items.length
            ? `Could not refresh ${plural}. The current list is kept.`
            : `Could not load ${plural}.`}{' '}
          <button
            className="btn"
            onClick={() => refresh({ showLoading: false })}
          >
            Retry
          </button>
        </div>
      )}
      {(snapshot || items.length > 0 || (!loading && !error)) && (
        <>
          <DragDropContext
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
                  >
                    <table
                      className={`table action-items-table${deletionEnabled ? ' action-items-table-deletable' : ''}`}
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
                          <th>Priority</th>
                          <th>Title</th>
                          <th>{showProject ? 'Project / tags' : 'Tags'}</th>
                          <th>Updated</th>
                          <th>Actions</th>
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
                                    <div className="flex-row">
                                      {reorderableView && (
                                        <button
                                          type="button"
                                          className="btn btn-sm action-item-drag"
                                          {...row.dragHandleProps}
                                          disabled={!canDrag}
                                          aria-label={`Reorder ${item.title}`}
                                          title="Drag to reorder; press Space to use the keyboard"
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
                                    <DateCell date={item.updated_at} />
                                  </td>
                                  <td>
                                    <div className="flex-row action-item-actions">
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
                        {displayed.length === 0 && (
                          <tr>
                            <td colSpan={5} className="loading">
                              No {status === 'all' ? '' : `${status} `}
                              {plural} found.
                            </td>
                          </tr>
                        )}
                        {provided.placeholder}
                      </tbody>
                    </table>
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
      )}
    </>
  );
}
