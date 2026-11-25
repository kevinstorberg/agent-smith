import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
  type ReactNode,
} from 'react';
import { api, type ActionItemEpic, type ActionItemRow } from '../api';
import type { ActionItemGroupedQueue } from '../hooks/useActionItemGroupedQueue';
import { useApiRead } from '../hooks/useApiRead';
import { ActionItemIcon } from './ActionItemIcon';
import { ActionDisclosure } from './ActionDisclosure';
import { ActionItemEpicSelect } from './ActionItemEpicSelect';

function useEpicEditor(
  queue: ActionItemGroupedQueue,
  trigger: RefObject<HTMLElement | null>,
  scope?: RefObject<HTMLElement | null>,
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
    if (
      element?.isConnected &&
      (document.activeElement === document.body ||
        (scope?.current ?? element?.parentElement)?.contains(
          document.activeElement,
        ))
    )
      element.focus({ preventScroll: true });
  }, [open, queue.editing, queue.busy, trigger, scope]);
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
          (scope?.current ?? trigger.current?.parentElement)?.contains(
            document.activeElement,
          ),
        );
      setOpen(false);
      setEditing(false);
    },
  };
}

export function EpicNameForm({
  initial = '',
  label = 'Epic name',
  lockedTitle,
  busy,
  onSave,
  onCancel,
}: {
  initial?: string;
  label?: string;
  lockedTitle?: string;
  busy: boolean;
  onSave: (title: string) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(initial);
  const name = lockedTitle ?? title;
  return (
    <form
      className="epic-name-form"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!busy && name.trim() && (await onSave(name.trim()))) onCancel();
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
          value={name}
          readOnly={lockedTitle !== undefined}
          disabled={busy}
          onChange={(event) => {
            if (lockedTitle === undefined) setTitle(event.target.value);
          }}
        />
      </label>
      <button className="btn btn-primary" disabled={busy || !name.trim()}>
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
  const receipt = queue.epicCreateReceipt;
  const setFormMounted = queue.setEpicCreateFormMounted;
  useEffect(() => {
    setFormMounted(true);
    return () => setFormMounted(false);
  }, [setFormMounted]);
  return (
    <>
      {item && <p>This action item will be the first item in the new Epic.</p>}
      <EpicNameForm
        initial={item?.title}
        busy={queue.busy}
        lockedTitle={receipt?.title}
        onCancel={() => {
          queue.cancelEpicCreation();
          onClose();
        }}
        onSave={async (title) => {
          if (!queue.canSubmit()) return false;
          const payload = receipt ?? {
            title,
            request_id: crypto.randomUUID(),
            ...(item
              ? { item_id: item.id, membership: queue.membership(item) }
              : {}),
          };
          return queue.createEpic(payload);
        }}
      />
      {receipt && !queue.busy && (
        <p>Retry “{receipt.title}” or cancel to start again.</p>
      )}
    </>
  );
}

export function EpicCreationRetry({
  queue,
}: {
  queue: ActionItemGroupedQueue;
}) {
  const retry = useRef<HTMLButtonElement>(null);
  const receipt = queue.epicCreateReceipt;
  const visible = receipt !== null && !queue.epicCreateFormMounted;
  useEffect(() => {
    if (
      visible &&
      !queue.busy &&
      document.activeElement === document.body &&
      !retry.current?.disabled
    )
      retry.current?.focus({ preventScroll: true });
  }, [visible, queue.busy]);
  if (!visible) return null;
  return (
    <div className="card" role="group" aria-label="Unfinished Epic creation">
      <p>Creation of “{receipt.title}” wasn’t confirmed.</p>
      <div className="flex-row">
        <button
          ref={retry}
          type="button"
          className="btn"
          disabled={queue.busy || !queue.canSubmit()}
          onClick={() => {
            void queue.createEpic(receipt);
          }}
        >
          {queue.busy ? 'Saving…' : 'Retry'}
        </button>
        <button
          type="button"
          className="btn"
          disabled={queue.busy}
          onClick={queue.cancelEpicCreation}
        >
          Cancel retry
        </button>
      </div>
    </div>
  );
}

export function NewEpicControl({
  queue,
  item,
}: {
  queue: ActionItemGroupedQueue;
  item?: ActionItemRow;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const { open, start, close } = useEpicEditor(queue, trigger);
  return (
    <div className="new-epic-control">
      <button
        ref={trigger}
        className={item ? 'btn btn-sm' : 'btn'}
        disabled={queue.freezeControls || !queue.canAct()}
        onClick={start}
      >
        {item ? 'Create Epic from this item' : 'New Epic'}
      </button>
      {open && <EpicCreateForm queue={queue} item={item} onClose={close} />}
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
  const [creating, setCreating] = useState(false);
  const selected = creating ? 'new' : String(queue.parentId(item) ?? '');
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
      <ActionItemEpicSelect
        label={
          queue.parentId(item) === null ? 'Add to Epic' : 'Move to another Epic'
        }
        ariaLabel="Move to Epic"
        autoFocus
        allowCreate
        value={selected}
        epics={read.data?.items ?? []}
        disabled={queue.busy || read.loading || Boolean(read.error)}
        onChange={async (value) => {
          setCreating(value === 'new');
          if (value === 'new') return;
          const destination = value
            ? read.data?.items.find((epic) => String(epic.id) === value)
            : null;
          if (value && !destination) return;
          if (await queue.setEpic(item, destination ?? null)) onClose();
        }}
      />
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
  text = false,
}: {
  queue: ActionItemGroupedQueue;
  item: ActionItemRow;
  text?: boolean;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const { open, start, close } = useEpicEditor(queue, trigger);
  const grouped = queue.parentId(item) !== null;
  const label = grouped ? 'Move to another Epic' : 'Add to Epic';
  return (
    <div className="epic-membership-control">
      <button
        ref={trigger}
        type="button"
        className={`btn btn-sm${text ? '' : ' action-item-icon-button'}`}
        aria-label={`Move ${item.title} to Epic`}
        title={label}
        disabled={queue.freezeControls || !queue.canAct()}
        onClick={start}
      >
        {text ? label : <ActionItemIcon name="epic" />}
      </button>
      {grouped && (
        <button
          type="button"
          className="btn btn-sm"
          aria-label={`Move ${item.title} out of Epic`}
          disabled={queue.freezeControls || !queue.canAct()}
          onClick={() => {
            if (queue.canAct()) void queue.setEpic(item, null);
          }}
        >
          Move out of Epic
        </button>
      )}
      <NewEpicControl queue={queue} item={item} />
      {open && <EpicPicker queue={queue} item={item} onClose={close} />}
    </div>
  );
}

export function EpicActions({
  queue,
  epic,
  children,
}: {
  queue: ActionItemGroupedQueue;
  epic: ActionItemEpic;
  children?: ReactNode | ((close: () => void) => ReactNode);
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const scope = useRef<HTMLDivElement>(null);
  const { open: renaming, start, close } = useEpicEditor(queue, trigger, scope);
  return (
    <div ref={scope} className="epic-action-controls">
      <ActionDisclosure
        label={`Actions for Epic ${epic.title}`}
        triggerRef={trigger}
        disabled={queue.freezeControls || !queue.canAct()}
        dismissible={!queue.busy && !queue.editing}
        resetKey={`${queue.view}:${epic.id}:${epic.revision}:${Boolean(queue.snapshot)}`}
      >
        {(closeActions) => (
          <>
            <button
              type="button"
              className="btn btn-sm"
              disabled={queue.freezeControls}
              onClick={() => {
                closeActions();
                start();
              }}
            >
              Rename Epic
            </button>
            {typeof children === 'function' ? children(closeActions) : children}
            <button
              type="button"
              className="btn btn-sm btn-danger"
              disabled={queue.freezeControls}
              onClick={() => {
                closeActions();
                if (
                  confirm(
                    `Delete Epic “${epic.title}”? Its action items will be kept and moved out of the Epic.`,
                  )
                )
                  void queue.removeEpic(epic);
              }}
            >
              Delete Epic
            </button>
          </>
        )}
      </ActionDisclosure>
      {renaming && (
        <EpicNameForm
          initial={epic.title}
          busy={queue.busy}
          onCancel={close}
          onSave={(title) => queue.renameEpic(epic, title)}
        />
      )}
    </div>
  );
}
