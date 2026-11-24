import { Fragment } from 'react';
import { DragDropContext, Draggable, Droppable } from '@hello-pangea/dnd';
import type {
  ActionItemEpicGroup,
  ActionItemQueueEntry,
  ActionItemSort,
  ActionItemRow,
} from '../api';
import {
  queueIdentity,
  type ActionItemGroupedQueue as GroupedQueue,
} from '../hooks/useActionItemGroupedQueue';
import {
  ActionItemDescription,
  ActionItemQueueCells,
} from './ActionItemQueueRow';
import { ActionItemQueueHead } from './ActionItemQueueHead';
import { EpicActions, EpicMembershipControl } from './ActionItemEpicControls';
import { ActionItemIcon } from './ActionItemIcon';
import { Pagination } from './Pagination';
import './actionItemQueue.css';

function Columns() {
  return (
    <colgroup>
      <col className="action-priority-column" />
      <col />
      <col className="action-topics-column" />
      <col className="action-updated-column" />
      <col className="action-controls-column" />
    </colgroup>
  );
}

function TaskEntry({
  entry,
  index,
  queue,
  onEdit,
}: {
  entry: ActionItemQueueEntry;
  index: number;
  queue: GroupedQueue;
  onEdit: (item: ActionItemRow) => void;
}) {
  const item = { ...entry.item, priority: entry.position };
  return (
    <Draggable
      draggableId={queueIdentity(entry)}
      index={index}
      isDragDisabled={!queue.dragSurfaceEnabled}
      disableInteractiveElementBlocking
    >
      {(row, state) => (
        <Fragment>
          <tr
            ref={row.innerRef}
            {...row.draggableProps}
            className="action-item-row"
            aria-busy={queue.pendingId === item.id}
            style={{
              ...row.draggableProps.style,
              background: state.isDragging ? 'var(--surface-hover)' : undefined,
            }}
          >
            <ActionItemQueueCells
              item={item}
              row={row}
              state={state}
              queue={queue}
              onEdit={onEdit}
              showDueDate
              showMoveActions
              membership={<EpicMembershipControl queue={queue} item={item} />}
            />
          </tr>
          {queue.expandedId === item.id && (
            <tr className="evidence-row-expanded">
              <td colSpan={5}>
                <ActionItemDescription
                  key={`${item.id}:${item.revision}`}
                  item={item}
                  get={queue.source.get}
                />
              </td>
            </tr>
          )}
        </Fragment>
      )}
    </Draggable>
  );
}

function EpicEntry({
  group,
  index,
  queue,
  onEdit,
}: {
  group: ActionItemEpicGroup;
  index: number;
  queue: GroupedQueue;
  onEdit: (item: ActionItemRow) => void;
}) {
  const { epic } = group;
  const open = queue.isOpen(epic.id);
  return (
    <Draggable
      draggableId={queueIdentity(group)}
      index={index}
      isDragDisabled={!queue.dragSurfaceEnabled || !queue.reorderableView}
      disableInteractiveElementBlocking
    >
      {(row, state) => (
        <tr
          ref={row.innerRef}
          {...row.draggableProps}
          className="action-item-epic-row"
          style={{
            ...row.draggableProps.style,
            background: state.isDragging ? 'var(--surface-hover)' : undefined,
          }}
        >
          <td colSpan={5}>
            <section aria-label={`Epic ${epic.title}`}>
              <div className="action-item-epic-heading">
                <div className="action-item-epic-identity">
                  {queue.reorderableView && (
                    <button
                      type="button"
                      className="btn btn-sm action-item-drag"
                      {...row.dragHandleProps}
                      disabled={!queue.canDrag}
                      aria-label={`Reorder Epic ${epic.title}`}
                      title="Drag the whole Epic; press Space to use the keyboard"
                    >
                      ⠿
                    </button>
                  )}
                  <span
                    className="action-item-priority"
                    aria-label={`Epic priority ${epic.position}`}
                  >
                    {queue.savingOrder ? '…' : epic.position}
                  </span>
                  <button
                    type="button"
                    className="inline-clear epic-toggle"
                    disabled={queue.freezeControls}
                    aria-expanded={open}
                    aria-controls={`epic-children-${epic.id}`}
                    onClick={() => queue.toggle(epic.id)}
                  >
                    <span aria-hidden="true">{open ? '⌄' : '›'}</span>
                    {epic.title}
                  </button>
                  <span className="epic-matching-count">
                    {group.matching_count} of {group.total_count} matching
                  </span>
                </div>
                <div className="action-item-epic-actions">
                  {queue.reorderableView &&
                    (['top', 'bottom'] as const).map((edge) => (
                      <button
                        key={edge}
                        className="btn btn-sm action-item-icon-button"
                        aria-label={`Move Epic ${epic.title} to ${edge}`}
                        title={`Move Epic to ${edge}`}
                        disabled={!queue.canMoveRoot(group, edge)}
                        onClick={() => void queue.moveRoot(group, edge)}
                      >
                        <ActionItemIcon name={edge} />
                      </button>
                    ))}
                  <EpicActions queue={queue} epic={epic} />
                </div>
              </div>
              {open && (
                <div id={`epic-children-${epic.id}`} className="epic-children">
                  <table
                    className="table action-items-table"
                    aria-label={`Action items in Epic ${epic.title}`}
                  >
                    <Columns />
                    <thead className="visually-hidden">
                      <tr>
                        {[
                          'Priority',
                          'Title',
                          'Project / Tags',
                          'Due date',
                          'Actions',
                        ].map((label) => (
                          <th key={label} scope="col">
                            {label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <Droppable
                      droppableId={`epic:${epic.id}`}
                      type={`EPIC:${epic.id}`}
                      isDropDisabled={!queue.reorderableView || !queue.canDrag}
                    >
                      {(provided) => (
                        <tbody
                          ref={provided.innerRef}
                          {...provided.droppableProps}
                        >
                          {group.children.map((entry, childIndex) => (
                            <TaskEntry
                              key={entry.entry_id}
                              entry={entry}
                              index={childIndex}
                              queue={queue}
                              onEdit={onEdit}
                            />
                          ))}
                          {provided.placeholder}
                          {group.children.length === 0 && (
                            <tr>
                              <td colSpan={5} className="epic-empty">
                                No matching action items in this Epic.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      )}
                    </Droppable>
                  </table>
                </div>
              )}
            </section>
          </td>
        </tr>
      )}
    </Draggable>
  );
}

export function ActionItemGroupedQueue({
  queue,
  status,
  sort,
  onSort,
  onEdit,
}: {
  queue: GroupedQueue;
  status: string;
  sort: ActionItemSort;
  onSort: (sort: ActionItemSort) => void;
  onEdit: (item: ActionItemRow) => void;
}) {
  const current = queue.dataCurrent && !queue.criteriaPending && !queue.error;
  return (
    <>
      <span role="status" aria-live="polite" className="visually-hidden">
        {queue.savingOrder
          ? 'Saving order…'
          : queue.pendingId !== null
            ? 'Saving action item…'
            : queue.snapshot?.project
              ? `Move ${queue.snapshot.items.find((item) => `item:${item.id}` === queue.snapshot?.itemId)?.title ?? 'action item'} to ${queue.snapshot.project}. Press Space to drop, or Escape to cancel.`
              : ''}
      </span>
      {queue.initialLoading && <p className="loading">Loading action items…</p>}
      {queue.error && (
        <div role="alert" className="card">
          {queue.items.length
            ? 'Could not refresh action items. The current list is kept.'
            : 'Could not load action items.'}{' '}
          <button className="btn" onClick={() => queue.refresh()}>
            Retry
          </button>
        </div>
      )}
      {queue.reviewError && <p role="alert">{queue.reviewError}</p>}
      <DragDropContext
        onBeforeCapture={() => queue.setExpanded(null)}
        onDragStart={queue.startDrag}
        onDragEnd={queue.endDrag}
        dragHandleUsageInstructions="Press Space to lift, Up and Down to reorder within this list, Space to drop, or Escape to cancel. For an action item, Left and Right choose a project. Change Epic membership with Move to Epic."
      >
        <div
          className="action-items-container action-item-grouped-container"
          role="region"
          aria-label="action items list"
          tabIndex={0}
        >
          <table
            className="table action-items-table action-item-grouped-table"
            aria-busy={!current && (queue.loading || !queue.error)}
          >
            <Columns />
            <ActionItemQueueHead
              sort={sort}
              onSort={onSort}
              current={current}
              disabled={queue.freezeControls}
              status={status}
              showDueDate
            />
            <Droppable
              droppableId="action-items"
              type="ROOT"
              isDropDisabled={!queue.canDrag || !queue.reorderableView}
            >
              {(provided) => (
                <tbody ref={provided.innerRef} {...provided.droppableProps}>
                  {queue.roots.map((root, index) =>
                    root.kind === 'item' ? (
                      <TaskEntry
                        key={root.entry_id}
                        entry={root}
                        index={index}
                        queue={queue}
                        onEdit={onEdit}
                      />
                    ) : (
                      <EpicEntry
                        key={root.epic.entry_id}
                        group={root}
                        index={index}
                        queue={queue}
                        onEdit={onEdit}
                      />
                    ),
                  )}
                  {provided.placeholder}
                </tbody>
              )}
            </Droppable>
          </table>
          {queue.roots.length === 0 && current && !queue.loading && (
            <p className="loading" role="status">
              No {status === 'all' ? '' : `${status} `}action items found.
            </p>
          )}
        </div>
      </DragDropContext>
      {current && (
        <p className="epic-queue-summary">
          {queue.total} items and Epics · {queue.matchingCount} matching Action
          Items
        </p>
      )}
      <Pagination
        total={queue.total}
        limit={queue.limit}
        offset={queue.offset}
        disabled={queue.freezeControls}
        onPageChange={queue.setOffset}
        onLimitChange={queue.setLimit}
      />
    </>
  );
}
