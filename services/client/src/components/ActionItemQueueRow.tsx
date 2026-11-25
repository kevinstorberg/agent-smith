import { useCallback, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import type {
  DraggableProvided,
  DraggableStateSnapshot,
} from '@hello-pangea/dnd';
import type { ActionItem, ActionItemRow } from '../api';
import type { ActionItemQueue } from '../hooks/useActionItemQueue';
import { useApiRead } from '../hooks/useApiRead';
import { DateCell } from './table';
import { ActionItemStatusButton } from './ActionItemStatusButton';
import { ActionItemIcon } from './ActionItemIcon';
import { ActionDisclosure } from './ActionDisclosure';
import { ActionItemTitleText, ActionItemTopics } from './ActionItemTaskSummary';

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

export function ActionItemDescription({
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

export type ActionItemRowQueue = Pick<
  ActionItemQueue,
  | 'snapshot'
  | 'savingOrder'
  | 'reorderableView'
  | 'projectAssignment'
  | 'canDrag'
  | 'expandedId'
  | 'busy'
  | 'freezeControls'
  | 'canAct'
  | 'setExpanded'
  | 'view'
  | 'loading'
  | 'error'
  | 'changeStatus'
  | 'canMoveToEdge'
  | 'moveToEdge'
  | 'deletionEnabled'
  | 'canRemove'
  | 'removeItem'
> & {
  editing?: boolean;
  moveScopeLabel?: (item: ActionItemRow, edge: 'top' | 'bottom') => string;
};

export function ActionItemQueueCells({
  item,
  row,
  state,
  queue,
  onEdit,
  noun = 'action item',
  showProject = true,
  showDueDate = false,
  showUpdated = !showDueDate,
  showMoveActions = false,
  compactActions = false,
  hideDragHandles = false,
  epicTitle = null,
  showEpicContext = false,
  membership,
  decorations,
}: {
  item: ActionItemRow;
  row: DraggableProvided;
  state: DraggableStateSnapshot;
  queue: ActionItemRowQueue;
  onEdit: (item: ActionItemRow) => void;
  noun?: string;
  showProject?: boolean;
  showDueDate?: boolean;
  showUpdated?: boolean;
  showMoveActions?: boolean;
  compactActions?: boolean;
  hideDragHandles?: boolean;
  epicTitle?: string | null;
  showEpicContext?: boolean;
  membership?: ReactNode;
  decorations?: ReactNode;
}) {
  const {
    snapshot,
    savingOrder,
    reorderableView,
    projectAssignment,
    canDrag,
    expandedId,
    busy,
    freezeControls,
    canAct,
    setExpanded,
    view,
    loading,
    error,
    changeStatus,
    canMoveToEdge,
    moveToEdge,
    deletionEnabled,
    canRemove,
    removeItem,
  } = queue;
  const iconActions = showMoveActions && !compactActions;
  function secondaryActions(close: () => void = () => undefined) {
    const moves =
      showMoveActions &&
      reorderableView &&
      (['top', 'bottom'] as const).map((edge) => (
        <button
          key={edge}
          type="button"
          className={`btn btn-sm${iconActions ? ' action-item-icon-button' : ''}`}
          aria-label={`Move ${item.title} to ${edge}${queue.moveScopeLabel && epicTitle ? ' of Epic' : ''}`}
          title={
            queue.moveScopeLabel?.(item, edge) ??
            `Move to ${edge} of the matching action items`
          }
          disabled={!canMoveToEdge(item, edge)}
          onKeyDown={(event) => {
            if (!compactActions || event.key !== 'Escape')
              event.stopPropagation();
          }}
          onClick={(event) => {
            event.stopPropagation();
            close();
            void moveToEdge(item, edge);
          }}
        >
          {iconActions ? (
            <ActionItemIcon name={edge} />
          ) : (
            (queue.moveScopeLabel?.(item, edge) ?? `Move to ${edge}`)
          )}
        </button>
      ));
    const edit = (
      <button
        type="button"
        className={`btn btn-sm${iconActions ? ' action-item-icon-button' : ''}`}
        aria-label={`Edit ${item.title}`}
        title={iconActions ? 'Edit' : undefined}
        disabled={busy || freezeControls || !canAct()}
        onClick={(event) => {
          event.stopPropagation();
          if (canAct()) {
            close();
            onEdit(item);
          }
        }}
      >
        {iconActions ? <ActionItemIcon name="edit" /> : 'Edit'}
      </button>
    );
    const remove = deletionEnabled && (
      <button
        type="button"
        className={`btn btn-sm btn-danger${iconActions ? ' action-item-icon-button' : ''}`}
        aria-label={`Delete ${item.title}`}
        title={iconActions ? 'Delete' : undefined}
        disabled={!canRemove()}
        onKeyDown={(event) => {
          if (!compactActions || event.key !== 'Escape')
            event.stopPropagation();
        }}
        onClick={(event) => {
          event.stopPropagation();
          if (!canRemove()) return;
          close();
          if (confirm(`Delete ${noun} “${item.title}”?`)) void removeItem(item);
        }}
      >
        {iconActions ? <ActionItemIcon name="delete" /> : 'Delete'}
      </button>
    );
    return compactActions ? (
      <>
        {edit}
        {membership}
        {moves}
        {remove}
      </>
    ) : (
      <>
        {moves}
        {edit}
        {remove}
        {membership}
      </>
    );
  }
  return (
    <>
      <td className="action-priority-cell">
        {decorations}
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
          {!hideDragHandles && (reorderableView || projectAssignment) && (
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
            {savingOrder ? '…' : (item.priority ?? '—')}
          </span>
        </div>
      </td>
      <td className="action-title-cell">
        <button
          type="button"
          id={`action-title-${item.id}`}
          className="inline-clear action-item-title"
          aria-label={item.title}
          aria-expanded={expandedId === item.id}
          aria-controls={`action-description-${item.id}`}
          disabled={busy || freezeControls || !canAct()}
          onClick={(event) => {
            event.stopPropagation();
            if (canAct())
              setExpanded(
                expandedId === item.id ? null : { id: item.id, view },
              );
          }}
        >
          <span aria-hidden="true">{expandedId === item.id ? '⌄' : '›'}</span>
          <ActionItemTitleText emphasized={compactActions}>
            {item.title}
          </ActionItemTitleText>
        </button>
        {showEpicContext && (
          <div className="action-item-epic-context">
            {epicTitle ? `Epic: ${epicTitle}` : 'No Epic'}
          </div>
        )}
      </td>
      <td className="action-topics-cell">
        <ActionItemTopics
          item={item}
          showProject={showProject}
          quiet={compactActions}
        />
      </td>
      {showDueDate && (
        <td className="action-due-cell">
          {item.due_at ? (
            <DateCell date={item.due_at} format="long" />
          ) : compactActions ? (
            <span className="action-empty-date">
              <span aria-hidden="true">—</span>
              <span className="visually-hidden">No due date</span>
            </span>
          ) : (
            'No due date'
          )}
        </td>
      )}
      {showUpdated && (
        <td className="action-updated-cell">
          <DateCell date={item.updated_at} />
        </td>
      )}
      <td className="action-controls-cell">
        <div
          className={`flex-row action-item-actions${showMoveActions ? ' action-item-actions-icons' : ''}`}
        >
          <ActionItemStatusButton
            noun={noun}
            item={item}
            small
            iconOnly={showMoveActions}
            disabled={busy || freezeControls || loading || Boolean(error)}
            onChange={() => {
              void changeStatus(item);
            }}
          />
          {compactActions ? (
            <ActionDisclosure
              label={`More actions for ${item.title}`}
              disabled={busy || freezeControls || !canAct()}
              dismissible={!busy && !queue.editing}
              resetKey={`${view}:${item.id}:${item.revision}:${Boolean(snapshot)}`}
            >
              {secondaryActions}
            </ActionDisclosure>
          ) : (
            secondaryActions()
          )}
        </div>
      </td>
    </>
  );
}
