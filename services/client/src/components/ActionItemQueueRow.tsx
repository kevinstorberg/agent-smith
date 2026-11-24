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
>;

export function ActionItemQueueCells({
  item,
  row,
  state,
  queue,
  onEdit,
  noun = 'action item',
  showProject = true,
  showDueDate = false,
  showMoveActions = false,
  membership,
}: {
  item: ActionItemRow;
  row: DraggableProvided;
  state: DraggableStateSnapshot;
  queue: ActionItemRowQueue;
  onEdit: (item: ActionItemRow) => void;
  noun?: string;
  showProject?: boolean;
  showDueDate?: boolean;
  showMoveActions?: boolean;
  membership?: ReactNode;
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
  return (
    <>
      {' '}
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
            {savingOrder ? '…' : (item.priority ?? '—')}
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
          {item.title}
        </button>
      </td>
      <td>
        {showProject && item.project && (
          <span className="tag tag-project">{item.project}</span>
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
            <DateCell date={item.due_at} format="long" />
          ) : (
            'No due date'
          )
        ) : (
          <DateCell date={item.updated_at} />
        )}
      </td>
      <td>
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
          {showMoveActions &&
            reorderableView &&
            (['top', 'bottom'] as const).map((edge) => (
              <button
                key={edge}
                type="button"
                className="btn btn-sm action-item-icon-button"
                aria-label={`Move ${item.title} to ${edge}`}
                title={`Move to ${edge} of the matching action items`}
                disabled={!canMoveToEdge(item, edge)}
                onKeyDown={(event) => event.stopPropagation()}
                onClick={(event) => {
                  event.stopPropagation();
                  void moveToEdge(item, edge);
                }}
              >
                <ActionItemIcon name={edge} />
              </button>
            ))}
          <button
            type="button"
            className={`btn btn-sm${showMoveActions ? ' action-item-icon-button' : ''}`}
            aria-label={`Edit ${item.title}`}
            title={showMoveActions ? 'Edit' : undefined}
            disabled={busy || freezeControls || !canAct()}
            onClick={(event) => {
              event.stopPropagation();
              if (canAct()) onEdit(item);
            }}
          >
            {showMoveActions ? <ActionItemIcon name="edit" /> : 'Edit'}
          </button>
          {deletionEnabled && (
            <button
              type="button"
              className={`btn btn-sm btn-danger${showMoveActions ? ' action-item-icon-button' : ''}`}
              aria-label={`Delete ${item.title}`}
              title={showMoveActions ? 'Delete' : undefined}
              disabled={!canRemove()}
              onKeyDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                if (canRemove() && confirm(`Delete ${noun} “${item.title}”?`))
                  void removeItem(item);
              }}
            >
              {showMoveActions ? <ActionItemIcon name="delete" /> : 'Delete'}
            </button>
          )}
          {membership}
        </div>
      </td>
    </>
  );
}
