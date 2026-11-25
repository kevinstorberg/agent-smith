import { Fragment, type ReactNode, type CSSProperties } from 'react';
import { DragDropContext, Draggable, Droppable } from '@hello-pangea/dnd';
import type {
  ActionItemEpicGroup,
  ActionItemQueueEntry,
  ActionItemQueueRoot,
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
import {
  ActionItemQueueHead,
  ActionItemQueueSort,
} from './ActionItemQueueHead';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { EpicActions, EpicMembershipControl } from './ActionItemEpicControls';
import { Pagination } from './Pagination';
import './actionItemQueue.css';

function rootLiftStyle(
  queue: GroupedQueue,
  index: number,
  dragging: boolean,
): CSSProperties {
  const lift = queue.snapshot?.rootTask;
  // Keep all root units aligned while pointer gestures choose grouping or insertion targets.
  return lift && !dragging
    ? {
        transform:
          index > lift.index ? `translate(0px, ${lift.height}px)` : 'none',
        transition: 'none',
      }
    : {};
}

function RootOrderEdges({
  root,
  queue,
}: {
  root: ActionItemQueueRoot;
  queue: GroupedQueue;
}) {
  const identity = queueIdentity(root);
  const selected = queue.snapshot?.rootOrderTarget;
  const active = Boolean(
    queue.snapshot?.rootTask &&
    queue.reorderableView &&
    queue.snapshot.itemId !== identity,
  );
  return (
    <>
      {(['before', 'after'] as const).map((edge) => (
        <div
          key={edge}
          className="action-item-root-order-target"
          data-root-order-id={identity}
          data-root-order-edge={edge}
          data-active={active}
          data-selected={
            selected
              ? `${selected.anchor.kind}:${selected.anchor.id}` === identity &&
                selected.edge === edge
              : false
          }
          aria-hidden="true"
        >
          <span>
            Place {edge}{' '}
            {root.kind === 'epic' ? `Epic ${root.epic.title}` : root.item.title}
          </span>
        </div>
      ))}
    </>
  );
}

function Columns() {
  return (
    <colgroup>
      <col className="action-priority-column" />
      <col />
      <col className="action-topics-column" />
      <col className="action-due-column" />
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
  const item = { ...entry.item, priority: queue.displayPriority(entry) };
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
              ...(entry.parent_epic_id === null
                ? rootLiftStyle(queue, index, state.isDragging)
                : {}),
              background: state.isDragging ? 'var(--surface-hover)' : undefined,
            }}
          >
            <ActionItemQueueCells
              item={item}
              row={row}
              state={state}
              queue={queue}
              onEdit={onEdit}
              decorations={
                entry.parent_epic_id === null ? (
                  <RootOrderEdges root={entry} queue={queue} />
                ) : undefined
              }
              showDueDate
              showUpdated
              showMoveActions
              compactActions
              hideDragHandles={queue.taskView}
              epicTitle={queue.parentEpic(item)?.title ?? null}
              showEpicContext={queue.taskView}
              membership={
                <EpicMembershipControl queue={queue} item={item} text />
              }
            />
          </tr>
          {queue.expandedId === item.id && (
            <tr className="evidence-row-expanded">
              <td colSpan={6}>
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
  heading,
}: {
  group: ActionItemEpicGroup;
  index: number;
  queue: GroupedQueue;
  onEdit: (item: ActionItemRow) => void;
  heading: ReactNode;
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
            ...rootLiftStyle(queue, index, state.isDragging),
            background: state.isDragging ? 'var(--surface-hover)' : undefined,
          }}
        >
          <td colSpan={6}>
            <RootOrderEdges root={group} queue={queue} />
            <section
              className="action-item-epic-group"
              data-expanded={open}
              aria-label={`Epic ${epic.title}`}
              data-epic-drop-target={epic.id}
              data-drop-selected={
                queue.snapshot?.epicTarget?.epic?.id === epic.id
              }
              tabIndex={-1}
            >
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
                    {group.matching_count === group.total_count
                      ? `${group.total_count} ${group.total_count === 1 ? 'item' : 'items'}`
                      : `${group.matching_count} of ${group.total_count} matching`}
                  </span>
                </div>
                <div className="action-item-epic-actions">
                  <EpicActions queue={queue} epic={epic}>
                    {(close) => (
                      <>
                        {queue.reorderableView &&
                          (['top', 'bottom'] as const).map((edge) => (
                            <button
                              key={edge}
                              type="button"
                              className="btn btn-sm"
                              aria-label={`Move Epic ${epic.title} to ${edge}`}
                              disabled={!queue.canMoveRoot(group, edge)}
                              onClick={() => {
                                close();
                                void queue.moveRoot(group, edge);
                              }}
                            >
                              Move Epic to {edge}
                            </button>
                          ))}
                      </>
                    )}
                  </EpicActions>
                </div>
              </div>
              {open && (
                <div id={`epic-children-${epic.id}`} className="epic-children">
                  <table
                    className="table action-items-table"
                    aria-label={`Action items in Epic ${epic.title}`}
                  >
                    <Columns />
                    {heading}
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
                              <td colSpan={6} className="epic-empty">
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
  const { epicTargetsRef } = queue;
  const externalMovement = queue.externalMovement;
  const compact = useMediaQuery('(max-width: 1100px)');
  const heading = (
    <ActionItemQueueHead
      sort={sort}
      onSort={onSort}
      current={current}
      disabled={queue.freezeControls}
      status={status}
      showDueDate
      showUpdated
      staticLabels={compact}
      taskView={queue.taskView}
    />
  );
  const childHeading = (
    <ActionItemQueueHead
      sort={sort}
      onSort={onSort}
      current={current}
      disabled={queue.freezeControls}
      status={status}
      showDueDate
      showUpdated
      staticLabels
    />
  );
  return (
    <>
      <span role="status" aria-live="polite" className="visually-hidden">
        {queue.savingOrder
          ? 'Saving order…'
          : queue.pendingId !== null
            ? 'Saving action item…'
            : externalMovement
              ? `${externalMovement}. Press Space to drop, or Escape to cancel.`
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
      {compact && (
        <ActionItemQueueSort
          sort={sort}
          onSort={onSort}
          status={status}
          disabled={queue.freezeControls}
        />
      )}
      <DragDropContext
        onBeforeCapture={() => queue.setExpanded(null)}
        onDragStart={(start) => queue.startDrag(start)}
        onDragUpdate={(update, provided) => {
          const movement = queue.externalDragAnnouncement();
          // External targets can change without a new SDK impact, so their live region owns updates.
          if (movement) provided.announce('');
          else if (
            !update.destination &&
            update.draggableId.startsWith('item:')
          )
            provided.announce(
              'Choose an Epic header, No Epic, or a project to move this item. Escape cancels.',
            );
        }}
        onDragEnd={(result, provided) => {
          const movement = queue.externalDragAnnouncement();
          if (movement)
            provided.announce(
              result.reason === 'CANCEL'
                ? 'Action item move canceled.'
                : `${movement}. Checking the current list.`,
            );
          return queue.endDrag(result);
        }}
        dragHandleUsageInstructions="Press Space to lift, Up and Down to reorder within this list, Space to drop, or Escape to cancel. For an action item, Left and Right choose a project; Shift plus Left or Right chooses an Epic or No Epic."
      >
        <div
          ref={epicTargetsRef}
          data-dragging={Boolean(queue.snapshot)}
          className="action-items-container action-item-grouped-container"
          role="region"
          aria-label="action items list"
          tabIndex={0}
        >
          <div
            className="action-item-no-epic-target"
            data-epic-drop-target="none"
            data-active={Boolean(
              queue.snapshot?.epics?.some((target) => target.epic === null),
            )}
            data-drop-selected={queue.snapshot?.epicTarget?.epic === null}
            tabIndex={-1}
          >
            No Epic — drop to move out
          </div>
          <table
            className="table action-items-table action-item-grouped-table"
            aria-busy={!current && (queue.loading || !queue.error)}
          >
            <caption className="visually-hidden">
              {queue.taskView
                ? 'All matching Action Items, including tasks in Epics. Priority shows the global task rank.'
                : 'Column sorting orders this list and the action items within each Epic.'}
            </caption>
            <Columns />
            {heading}
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
                        heading={childHeading}
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
          {queue.taskView
            ? `${queue.total} matching Action Items`
            : `${queue.total} items and Epics · ${queue.matchingCount} matching Action Items`}
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
