import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from 'react';
import {
  api,
  type ActionItemEpic,
  type ActionItemEpicCreate,
  type ActionItemRow,
} from '../api';
import type { ActionItemGroupedQueue } from '../hooks/useActionItemGroupedQueue';
import { useApiRead } from '../hooks/useApiRead';
import { ActionItemIcon } from './ActionItemIcon';

function useEpicEditor(
  queue: ActionItemGroupedQueue,
  trigger: RefObject<HTMLElement | null>,
) {
  const [open, setOpen] = useState(false);
  const restore = useRef(false);
  const setEditing = queue.setEditing;
  useEffect(() => {
    if (!open) return;
    return () => setEditing(false);
  }, [open, setEditing]);
  useLayoutEffect(() => {
    if (open || queue.editing || queue.busy || !restore.current) return;
    restore.current = false;
    const element = trigger.current;
    const target =
      element instanceof HTMLDetailsElement
        ? element.querySelector('summary')
        : element;
    if (
      target?.isConnected &&
      (document.activeElement === document.body ||
        element?.parentElement?.contains(document.activeElement))
    )
      target.focus({ preventScroll: true });
  }, [open, queue.editing, queue.busy, trigger]);
  return {
    open,
    start: () => {
      setOpen(true);
      setEditing(true);
    },
    close: () => {
      restore.current =
        document.activeElement === document.body ||
        Boolean(
          trigger.current?.parentElement?.contains(document.activeElement),
        );
      setOpen(false);
      setEditing(false);
    },
  };
}

export function EpicNameForm({
  initial = '',
  label = 'Epic name',
  busy,
  onSave,
  onCancel,
}: {
  initial?: string;
  label?: string;
  busy: boolean;
  onSave: (title: string) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(initial);
  return (
    <form
      className="epic-name-form"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!busy && title.trim() && (await onSave(title.trim()))) onCancel();
      }}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === 'Escape' && !busy) onCancel();
      }}
    >
      <label>
        <span className="form-label">{label}</span>
        <input
          className="input"
          autoFocus
          required
          maxLength={200}
          value={title}
          disabled={busy}
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>
      <button className="btn btn-primary" disabled={busy || !title.trim()}>
        Save Epic
      </button>
      <button type="button" className="btn" disabled={busy} onClick={onCancel}>
        Cancel
      </button>
    </form>
  );
}

function EpicCreateForm({
  queue,
  item,
  onClose,
}: {
  queue: ActionItemGroupedQueue;
  item?: ActionItemRow;
  onClose: () => void;
}) {
  const receipt = useRef<ActionItemEpicCreate | null>(null);
  return (
    <EpicNameForm
      busy={queue.busy}
      onCancel={onClose}
      onSave={async (title) => {
        if (!receipt.current || receipt.current.title !== title)
          receipt.current = {
            title,
            request_id: crypto.randomUUID(),
            ...(item
              ? { item_id: item.id, membership: queue.membership(item) }
              : {}),
          };
        return queue.createEpic(receipt.current);
      }}
    />
  );
}

export function NewEpicControl({ queue }: { queue: ActionItemGroupedQueue }) {
  const trigger = useRef<HTMLButtonElement>(null);
  const { open, start, close } = useEpicEditor(queue, trigger);
  return (
    <div className="new-epic-control">
      <button
        ref={trigger}
        className="btn"
        disabled={queue.freezeControls || !queue.canAct()}
        onClick={start}
      >
        New Epic
      </button>
      {open && <EpicCreateForm queue={queue} onClose={close} />}
    </div>
  );
}

function EpicPicker({
  queue,
  item,
  onClose,
}: {
  queue: ActionItemGroupedQueue;
  item: ActionItemRow;
  onClose: () => void;
}) {
  const read = useApiRead(api.actionItemEpics.list);
  const [selected, setSelected] = useState(String(queue.parentId(item) ?? ''));
  return (
    <div
      className="epic-picker"
      role="group"
      aria-label={`Epic for ${item.title}`}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === 'Escape' && !queue.busy) onClose();
      }}
    >
      {read.error && (
        <p role="alert">
          Could not load Epics.{' '}
          <button type="button" className="btn" onClick={() => read.refresh()}>
            Retry
          </button>
        </p>
      )}
      <label>
        <span className="form-label">Move to Epic</span>
        <select
          className="input"
          autoFocus
          value={selected}
          disabled={queue.busy || read.loading || Boolean(read.error)}
          onChange={async (event) => {
            const value = event.target.value;
            setSelected(value);
            if (value === 'new') return;
            const destination = value
              ? read.data?.items.find((epic) => String(epic.id) === value)
              : null;
            if (value && !destination) return;
            if (await queue.setEpic(item, destination ?? null)) onClose();
          }}
        >
          <option value="">No Epic</option>
          {read.data?.items.map((epic) => (
            <option key={epic.id} value={epic.id}>
              {epic.title}
              {read.data!.items.filter((other) => other.title === epic.title)
                .length > 1
                ? ` #${epic.id}`
                : ''}
            </option>
          ))}
          <option value="new">New Epic…</option>
        </select>
      </label>
      {selected === 'new' ? (
        <EpicCreateForm queue={queue} item={item} onClose={onClose} />
      ) : (
        <button
          type="button"
          className="btn"
          disabled={queue.busy}
          onClick={onClose}
        >
          Cancel
        </button>
      )}
    </div>
  );
}

export function EpicMembershipControl({
  queue,
  item,
}: {
  queue: ActionItemGroupedQueue;
  item: ActionItemRow;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const { open, start, close } = useEpicEditor(queue, trigger);
  return (
    <div className="epic-membership-control">
      <button
        ref={trigger}
        type="button"
        className="btn btn-sm action-item-icon-button"
        aria-label={`Move ${item.title} to Epic`}
        title="Move to Epic"
        disabled={queue.freezeControls || !queue.canAct()}
        onClick={start}
      >
        <ActionItemIcon name="epic" />
      </button>
      {open && <EpicPicker queue={queue} item={item} onClose={close} />}
    </div>
  );
}

export function EpicActions({
  queue,
  epic,
}: {
  queue: ActionItemGroupedQueue;
  epic: ActionItemEpic;
}) {
  const trigger = useRef<HTMLDetailsElement>(null);
  const { open: renaming, start, close } = useEpicEditor(queue, trigger);
  return (
    <>
      <details ref={trigger} className="epic-menu">
        <summary
          aria-label={`Actions for Epic ${epic.title}`}
          aria-disabled={queue.freezeControls}
          onClick={(event) => {
            if (queue.freezeControls) event.preventDefault();
          }}
        >
          Epic actions
        </summary>
        <div>
          <button
            className="btn btn-sm"
            disabled={queue.freezeControls}
            onClick={() => {
              trigger.current!.open = false;
              start();
            }}
          >
            Rename Epic
          </button>
          <button
            className="btn btn-sm"
            disabled={queue.freezeControls}
            onClick={() => {
              if (
                confirm(
                  `Remove Epic “${epic.title}”? Its action items are kept and ungrouped.`,
                )
              )
                void queue.removeEpic(epic);
            }}
          >
            Remove Epic
          </button>
        </div>
      </details>
      {renaming && (
        <EpicNameForm
          initial={epic.title}
          busy={queue.busy}
          onCancel={close}
          onSave={(title) => queue.renameEpic(epic, title)}
        />
      )}
    </>
  );
}
