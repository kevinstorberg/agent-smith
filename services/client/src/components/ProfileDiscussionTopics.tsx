import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import ReactMarkdown from 'react-markdown';
import { api, ApiError } from '../api';
import type {
  ActionItemRow,
  ActionItemSort,
  ActionItemStatus,
  ProfileDiscussionTopic,
  ProfileDiscussionTopicCreate,
  ProfileDiscussionTopicPatch,
} from '../api';
import { useActionItemQueue } from '../hooks/useActionItemQueue';
import type { ActionItemQueueSource } from '../hooks/useActionItemQueue';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { actionItemTags } from '../utils/actionItems';
import {
  ACTION_ITEM_STATUSES,
  actionItemSortOptions,
  defaultActionItemSort,
  MAX_BODY_LENGTH,
  MAX_TITLE_LENGTH,
} from '../constants';
import { ActionItemQueueTable } from './ActionItemQueueTable';

interface Draft {
  title: string;
  description: string;
  tags: string;
  revision: number;
}

function TopicEditor({
  id,
  active,
  disabled,
  source,
  create,
  remove,
  onClose,
  onSaved,
}: {
  id: number | null;
  active: boolean;
  disabled: boolean;
  source: ActionItemQueueSource;
  create: (
    body: ProfileDiscussionTopicCreate,
  ) => Promise<ProfileDiscussionTopic>;
  remove: (id: number, revision: number) => Promise<unknown>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = id === null;
  const readItem = useCallback(
    () => (id === null ? Promise.resolve(null) : source.get(id)),
    [id, source],
  );
  const read = useApiRead(readItem, { enabled: active && !isNew });
  const latestItem = useRef(read.data);
  useLayoutEffect(() => {
    latestItem.current = read.data;
  }, [read.data]);
  const [draft, setDraft] = useState<Draft | null>(
    isNew ? { title: '', description: '', tags: '', revision: 0 } : null,
  );
  const [notice, setNotice] = useState<string | null>(null);
  const [conflictAfter, setConflictAfter] = useState<typeof read.data>(null);
  const [uncertain, setUncertain] = useState(false);
  const submission = useRef<ProfileDiscussionTopicCreate | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const mounted = useRef(false);
  const writing = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (read.data && !draft)
      setDraft({
        title: read.data.title,
        description: read.data.description,
        tags: read.data.tags.join(', '),
        revision: read.data.revision,
      });
  }, [read.data, draft]);
  useEffect(() => {
    if (active && dialog.current && !dialog.current.open)
      dialog.current.showModal();
  }, [active]);
  const changed = (failure: Error) => {
    if (!mounted.current) return;
    if (!isNew && failure instanceof ApiError && failure.status === 409) {
      setConflictAfter(latestItem.current);
      setNotice(
        'This discussion topic changed. Your draft is retained. Review the current saved version before saving again.',
      );
      void read.refresh({ showLoading: false });
    } else {
      setNotice(failure.message);
      if (isNew && submission.current) {
        if (failure instanceof ApiError && failure.status === 422) {
          submission.current = null;
          setUncertain(false);
        } else setUncertain(true);
      }
    }
  };
  const saved = () => {
    if (mounted.current) onSaved();
  };
  const creation = useApiMutation({
    mutationFn: create,
    onSuccess: saved,
    onError: changed,
  });
  const update = useApiMutation({
    mutationFn: (body: ProfileDiscussionTopicPatch) => source.update(id!, body),
    onSuccess: saved,
    onError: changed,
  });
  const deletion = useApiMutation({
    mutationFn: () =>
      remove(
        id!,
        conflictAfter === null ? draft!.revision : read.data!.revision,
      ),
    onSuccess: saved,
    onError: changed,
  });
  const saving = creation.loading || update.loading || deletion.loading;
  const currentAccepted =
    conflictAfter === null || (read.data !== conflictAfter && !read.error);
  const submit = async () => {
    if (
      !draft ||
      disabled ||
      writing.current ||
      saving ||
      !currentAccepted ||
      (!isNew && (read.loading || read.error))
    )
      return;
    const title = draft.title.trim();
    if (!title || title.length > MAX_TITLE_LENGTH) {
      setNotice(
        `Title is required and must be ${MAX_TITLE_LENGTH} characters or fewer.`,
      );
      return;
    }
    writing.current = true;
    try {
      if (isNew) {
        submission.current ??= {
          title,
          description: draft.description,
          tags: actionItemTags(draft.tags),
          request_id: crypto.randomUUID(),
        };
        await creation.mutate(submission.current);
      } else {
        await update.mutate({
          title,
          description: draft.description,
          tags: actionItemTags(draft.tags),
          expected_revision:
            conflictAfter === null ? draft.revision : read.data!.revision,
        });
      }
    } finally {
      writing.current = false;
    }
  };
  if (!active) return null;
  return (
    <dialog
      ref={dialog}
      className="meeting-participant-dialog"
      aria-label={isNew ? 'New discussion topic' : 'Edit discussion topic'}
      onCancel={(event) => {
        event.preventDefault();
        if (!saving && !writing.current) onClose();
      }}
    >
      <h3>{isNew ? 'New discussion topic' : 'Edit discussion topic'}</h3>
      {notice && <p role="alert">{notice}</p>}
      {!isNew && read.loading && !draft && (
        <p role="status">Loading discussion topic…</p>
      )}
      {!isNew && read.error && (
        <p role="alert">
          Could not refresh this discussion topic. Your draft is retained.{' '}
          <button type="button" className="btn" onClick={() => read.refresh()}>
            Retry refresh
          </button>
        </p>
      )}
      {draft && (
        <form
          className="participant-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label className="form-label" htmlFor="topic-title">
            Title
          </label>
          <input
            id="topic-title"
            className="input"
            autoFocus
            maxLength={MAX_TITLE_LENGTH}
            value={draft.title}
            disabled={saving || uncertain}
            onChange={(event) =>
              setDraft({ ...draft, title: event.target.value })
            }
          />
          <label className="form-label" htmlFor="topic-notes">
            Notes
          </label>
          <textarea
            id="topic-notes"
            className="input"
            rows={8}
            maxLength={MAX_BODY_LENGTH}
            value={draft.description}
            disabled={saving || uncertain}
            onChange={(event) =>
              setDraft({ ...draft, description: event.target.value })
            }
            placeholder="Optional notes; Markdown is supported."
          />
          <label className="form-label" htmlFor="topic-tags">
            Tags
          </label>
          <input
            id="topic-tags"
            className="input"
            value={draft.tags}
            disabled={saving || uncertain}
            onChange={(event) =>
              setDraft({ ...draft, tags: event.target.value })
            }
            placeholder="Tags, comma-separated"
          />
          {uncertain && (
            <p role="status">
              The save could not be confirmed. Retry Save to check the original
              submission.
            </p>
          )}
          {conflictAfter && (
            <section aria-label="Current saved discussion topic">
              <h4>Current saved version</h4>
              {!currentAccepted ? (
                <p>
                  Waiting for refreshed information. Your draft is retained.
                </p>
              ) : (
                <>
                  <strong>{read.data!.title}</strong>
                  <p>{read.data!.tags.join(', ') || 'No tags'}</p>
                  <div className="markdown-content">
                    <ReactMarkdown>
                      {read.data!.description || 'No notes added.'}
                    </ReactMarkdown>
                  </div>
                </>
              )}
            </section>
          )}
          <div className="flex-wrap">
            <button
              className="btn btn-primary"
              disabled={
                disabled ||
                saving ||
                !currentAccepted ||
                (!isNew && Boolean(read.loading || read.error))
              }
            >
              Save
            </button>
            {!isNew && (
              <button
                type="button"
                className="btn btn-danger"
                disabled={
                  disabled ||
                  saving ||
                  !currentAccepted ||
                  Boolean(read.loading || read.error)
                }
                onClick={() => {
                  if (
                    !writing.current &&
                    confirm(`Delete discussion topic “${read.data!.title}”?`)
                  ) {
                    writing.current = true;
                    void deletion.mutate().finally(() => {
                      writing.current = false;
                    });
                  }
                }}
              >
                Delete topic
              </button>
            )}
            <button
              type="button"
              className="btn"
              disabled={saving}
              onClick={() => {
                if (!writing.current) onClose();
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
      {!draft && (
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
      )}
    </dialog>
  );
}

export function ProfileDiscussionTopics({
  profileId,
  active,
  disabled,
  onBusyChange,
  onReload,
}: {
  profileId: string;
  active: boolean;
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
  onReload: () => void;
}) {
  const [status, setStatus] = useState<ActionItemStatus | 'all'>('open');
  const [sort, setSort] = useState<ActionItemSort>('manual');
  const [queryInput, setQueryInput] = useState('');
  const [tagsInput, setTagsInput] = useState('');
  const query = useDebouncedValue(queryInput.trim());
  const tags = useDebouncedValue(tagsInput.trim());
  const [edit, setEdit] = useState<{ id: number | null } | null>(null);
  const [identityChanged, setIdentityChanged] = useState(false);
  const reload = useRef(onReload);
  const mounted = useRef(false);
  const trigger = useRef<HTMLElement | null>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    reload.current = onReload;
  }, [onReload]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const resource = useMemo(() => {
    const verify = <T extends { profile_id: string }>(result: T): T => {
      if (result.profile_id !== profileId) {
        if (mounted.current) {
          setIdentityChanged(true);
          reload.current();
        }
        throw new Error(
          'This profile identity changed. Reload the canonical profile before changing discussion topics.',
        );
      }
      return result;
    };
    return {
      list: async (filters: Parameters<ActionItemQueueSource['list']>[0]) => {
        const { project: _project, ...scopedFilters } = filters;
        void _project;
        const page = verify(
          await api.profiles.topics.list(profileId, scopedFilters),
        );
        page.items.forEach(verify);
        return page;
      },
      get: async (id: number) =>
        verify(await api.profiles.topics.get(profileId, id)),
      update: async (
        id: number,
        body: Parameters<ActionItemQueueSource['update']>[1],
      ) => {
        const { project: _project, ...changes } = body;
        void _project;
        return verify(await api.profiles.topics.update(profileId, id, changes));
      },
      move: async (
        id: number,
        body: Parameters<ActionItemQueueSource['move']>[1],
      ) => verify(await api.profiles.topics.move(profileId, id, body)),
      create: async (body: ProfileDiscussionTopicCreate) =>
        verify(await api.profiles.topics.create(profileId, body)),
      remove: (id: number, revision: number) =>
        api.profiles.topics.remove(profileId, id, revision),
    };
  }, [profileId]);
  const criteriaPending =
    queryInput.trim() !== query || tagsInput.trim() !== tags;
  const queue = useActionItemQueue({
    source: resource,
    filters: {
      status,
      sort,
      q: query || undefined,
      tags: actionItemTags(tags),
    },
    criteria: JSON.stringify([profileId, status, sort, query, tags]),
    viewKey: JSON.stringify([profileId, status, sort, queryInput, tagsInput]),
    reorderableView: status === 'open' && sort === 'manual',
    criteriaPending,
    active,
    disabled: disabled || identityChanged,
    editing: Boolean(edit),
    noun: 'discussion topic',
  });
  const busy = Boolean(edit) || queue.busy || Boolean(queue.snapshot);
  useEffect(() => {
    onBusyChange(busy);
  }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange(false), [onBusyChange]);
  const open = (item?: ActionItemRow) => {
    if (!queue.canAct() || queue.loading || queue.error) return;
    trigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setEdit({ id: item?.id ?? null });
  };
  useEffect(() => {
    if (active && !edit && restoreFocus.current) {
      if (trigger.current?.isConnected) trigger.current.focus();
      restoreFocus.current = false;
    }
  }, [active, edit]);
  const close = () => {
    restoreFocus.current = true;
    setEdit(null);
  };
  const saved = () => {
    close();
    void queue.refresh({ showLoading: false });
  };
  return (
    <>
      {active && (
        <section aria-label="Discussion topics">
          <div className="page-header">
            <h3 className="section-title">Discussion topics</h3>
            <button
              className="btn btn-primary"
              disabled={
                disabled ||
                identityChanged ||
                busy ||
                queue.loading ||
                Boolean(queue.error)
              }
              onClick={() => open()}
            >
              New discussion topic
            </button>
          </div>
          <div
            className="sub-tabs"
            role="tablist"
            aria-label="Discussion topic status"
          >
            {ACTION_ITEM_STATUSES.map(([value, label]) => (
              <button
                key={value}
                role="tab"
                aria-selected={status === value}
                className={status === value ? 'active' : ''}
                disabled={queue.freezeControls}
                onClick={() => {
                  setStatus(value);
                  setSort(defaultActionItemSort(value));
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="profile-filters">
            <label>
              <span className="form-label">Search discussion topics</span>
              <input
                className="input"
                type="search"
                maxLength={1000}
                value={queryInput}
                disabled={queue.freezeControls}
                onChange={(event) => setQueryInput(event.target.value)}
                placeholder="Search title or notes…"
              />
            </label>
            <label>
              <span className="form-label">Filter tags</span>
              <input
                className="input"
                value={tagsInput}
                disabled={queue.freezeControls}
                onChange={(event) => setTagsInput(event.target.value)}
                placeholder="Tags, comma-separated"
              />
            </label>
            <label>
              <span className="form-label">Sort</span>
              <select
                className="input"
                value={sort}
                disabled={queue.freezeControls}
                onChange={(event) =>
                  setSort(event.target.value as ActionItemSort)
                }
              >
                {actionItemSortOptions(status).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {!queue.reorderableView && (
            <p className="text-muted-sm">
              To drag topics into order, use Open with Manual order; search and
              filters can stay applied.
            </p>
          )}
          {identityChanged ? (
            <p className="card" role="alert">
              This profile identity changed. Reload the profile to continue.{' '}
              <button className="btn" onClick={onReload}>
                Reload profile
              </button>
            </p>
          ) : (
            <ActionItemQueueTable
              queue={queue}
              status={status}
              scope={`profile-topics-${profileId}`}
              noun="discussion topic"
              plural="discussion topics"
              showProject={false}
              onEdit={(item) => open(item)}
            />
          )}
        </section>
      )}
      {edit && !identityChanged && (
        <TopicEditor
          key={edit.id ?? 'new'}
          id={edit.id}
          active={active}
          disabled={disabled}
          source={resource}
          create={resource.create}
          remove={resource.remove}
          onClose={close}
          onSaved={saved}
        />
      )}
    </>
  );
}
