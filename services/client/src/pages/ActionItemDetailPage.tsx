import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router';
import ReactMarkdown from 'react-markdown';
import { api, ApiError } from '../api';
import type { ActionItem, ActionItemCreate, ActionItemFields } from '../api';
import { DetailPageHeader } from '../components/DetailPageHeader';
import { DateCell } from '../components/table';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { useDetailPageEdit } from '../hooks/useDetailPageEdit';
import { usePolling } from '../hooks/usePolling';
import { useNotification } from '../context/useNotification';
import { MAX_BODY_LENGTH, MAX_TITLE_LENGTH } from '../constants';
import { actionItemTags } from '../utils/actionItems';

interface Draft { title: string; description: string; project: string; tags: string; revision: number }

export function ActionItemDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <ActionItemDetail key={id || 'new'} id={id} />;
}

function ActionItemDetail({ id }: { id?: string }) {
  const isNew = !id || id === 'new';
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { notify } = useNotification();
  const fetchItem = useCallback(() => isNew ? Promise.resolve(null) : api.actionItems.get(Number(id)), [id, isNew]);
  const read = useApiRead(fetchItem);
  const item = read.data;
  const form = useDetailPageEdit<Draft>({ isNew, onCancel: () => navigate('/action-items') });
  const { editing, editValues, setEditValue, startEditing: beginEditing } = form;
  const [conflictAfter, setConflictAfter] = useState<ActionItem | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [uncertainCreate, setUncertainCreate] = useState(false);
  const submission = useRef<ActionItemCreate | null>(null);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const latestItem = useRef(item);
  useEffect(() => { latestItem.current = item; }, [item]);

  const changed = (failure: Error) => {
    if (!mounted.current) return;
    if (failure instanceof ApiError && failure.status === 409 && !isNew) {
      setConflictAfter(latestItem.current);
      setNotice('This action item changed. Your draft is retained. Review the current saved version before saving again.');
      void read.refresh({ showLoading: false });
    } else {
      setNotice(failure.message);
      if (isNew && submission.current) {
        if (failure instanceof ApiError && failure.status === 422) { submission.current = null; setUncertainCreate(false); }
        else setUncertainCreate(true);
      }
    }
  };
  const create = useApiMutation({ mutationFn: api.actionItems.create,
    onSuccess: saved => { if (mounted.current) navigate(`/action-items/${saved.id}`, { replace: true }); }, onError: changed });
  const update = useApiMutation({ mutationFn: (body: ActionItemFields & { expected_revision: number }) => api.actionItems.update(Number(id), body),
    onSuccess: () => { if (mounted.current) { setNotice(null); setConflictAfter(null); form.cancelEditing(); void read.refresh({ showLoading: false }); } }, onError: changed });
  const status = useApiMutation({ mutationFn: () => api.actionItems.update(item!.id, {
    expected_revision: item!.revision, status: item!.status === 'open' ? 'completed' : 'open',
  }), onSuccess: () => { if (mounted.current) { setNotice(null); setConflictAfter(null); void read.refresh({ showLoading: false }); } }, onError: changed });
  const remove = useApiMutation({ mutationFn: () => api.actionItems.remove(item!.id, item!.revision),
    onSuccess: () => { if (mounted.current) navigate('/action-items'); }, onError: changed });
  const saving = create.loading || update.loading || status.loading || remove.loading;
  const rereadAccepted = conflictAfter === null || (item !== conflictAfter && !read.error);
  usePolling(() => read.refresh({ showLoading: false }), { enabled: !isNew && !editing && !saving && rereadAccepted });

  const startEditing = useCallback(() => {
    if (!item || saving || read.error) return;
    setNotice(null); setConflictAfter(null);
    beginEditing({ title: item.title, description: item.description, project: item.project || '', tags: item.tags.join(', '), revision: item.revision });
  }, [item, saving, read.error, beginEditing]);

  const directEdit = searchParams.get('edit') === '1';
  useEffect(() => {
    if (!directEdit || isNew || !item || saving || read.error) return;
    if (!editing) startEditing();
    setSearchParams(current => { const next = new URLSearchParams(current); next.delete('edit'); return next; }, { replace: true });
  }, [directEdit, isNew, item, saving, read.error, editing, startEditing, setSearchParams]);

  function save() {
    if (saving || !rereadAccepted) return;
    if (isNew && submission.current) { void create.mutate(submission.current); return; }
    const title = (editValues.title || '').trim();
    if (!title || title.length > MAX_TITLE_LENGTH) { notify(`Title is required and must be ${MAX_TITLE_LENGTH} characters or fewer.`, 'error'); return; }
    const fields = {
      title, description: editValues.description || '', project: editValues.project?.trim() || null,
      tags: actionItemTags(editValues.tags || ''),
    } satisfies ActionItemFields;
    setNotice(null);
    if (isNew) {
      submission.current = { ...fields, request_id: crypto.randomUUID() };
      void create.mutate(submission.current);
    } else {
      void update.mutate({ ...fields, expected_revision: conflictAfter === null ? editValues.revision! : item!.revision });
    }
  }

  if (!isNew && read.loading && !item) return <p className="loading">Loading action item…</p>;
  if (!isNew && !item) return <div className="card" role="alert">Could not load this action item.
    <button className="btn" onClick={() => read.refresh()}>Retry</button>
    <button className="btn" onClick={() => navigate('/action-items')}>Back to action items</button>
  </div>;

  return <div>
    <DetailPageHeader backTo={{ label: 'action items', path: '/action-items' }} editing={editing} saving={saving}
      disabled={saving || (!editing && (Boolean(read.error) || !rereadAccepted))} saveDisabled={!rereadAccepted}
      onEdit={startEditing} onSave={save} onCancel={() => { form.cancelEditing(); setNotice(null); setConflictAfter(null); }}
      onDelete={item ? () => { void remove.mutate(); } : undefined}
      deleteConfirmMessage={item ? `Delete action item “${item.title}”?` : undefined}
      onNavigateBack={() => navigate('/action-items')} />
    {notice && <div className="card" role="alert">{notice}</div>}
    {!isNew && read.error && <div className="card" role="alert">Could not refresh this action item. Your draft is retained.
      <button className="btn" onClick={() => read.refresh({ showLoading: false })}>Retry refresh</button>
    </div>}
    {editing ? <div className="card">
      <label className="form-label" htmlFor="action-title">Title</label>
      <input id="action-title" className="input" value={editValues.title || ''} disabled={saving || uncertainCreate}
        maxLength={MAX_TITLE_LENGTH} onChange={event => setEditValue('title', event.target.value)} autoFocus />
      <div className="filters" style={{ marginTop: 16 }}>
        <label><span className="form-label">Project</span><input className="input" maxLength={200}
          value={editValues.project || ''} disabled={saving || uncertainCreate} onChange={event => setEditValue('project', event.target.value)} placeholder="No project" /></label>
        <label><span className="form-label">Tags</span><input className="input" value={editValues.tags || ''}
          disabled={saving || uncertainCreate} onChange={event => setEditValue('tags', event.target.value)} placeholder="Tags, comma-separated" /></label>
      </div>
      <label className="form-label" htmlFor="action-description">Description</label>
      <textarea id="action-description" className="input" rows={12} maxLength={MAX_BODY_LENGTH} value={editValues.description || ''}
        disabled={saving || uncertainCreate} onChange={event => setEditValue('description', event.target.value)} placeholder="Optional details; Markdown is supported." />
      {uncertainCreate && <p role="status">The save could not be confirmed. Retry Save to check the original submission, or return to the list.</p>}
      {conflictAfter && <section className="card" aria-label="Current saved action item" style={{ marginTop: 16 }}>
        <h3>Current saved version</h3>
        {!rereadAccepted ? <><p>Waiting for refreshed information. Your draft is retained.</p>
          <button className="btn" onClick={() => read.refresh({ showLoading: false })}>Refresh current version</button></>
          : <><strong>{item!.title}</strong><p className="text-muted-sm">Project: {item!.project || 'None'} · Tags: {item!.tags.join(', ') || 'None'}</p>
            <div className="markdown-content"><ReactMarkdown>{item!.description || 'No description'}</ReactMarkdown></div></>}
      </section>}
    </div> : <>
      <div className="page-header"><h2 className="page-title">{item!.title}</h2>
        <button className="btn" disabled={saving || Boolean(read.error) || !rereadAccepted} onClick={() => { void status.mutate(); }}>
          {item!.status === 'completed' ? 'Reopen action item' : 'Mark complete'}
        </button>
      </div>
      <div className="flex-wrap" style={{ marginBottom: 16 }}>
        <span className="tag">{item!.status === 'completed' ? 'Completed' : 'Open'}</span>
        {item!.project && <span className="tag tag-project">{item!.project}</span>}
        {item!.tags.map(tag => <span className="tag" key={tag}>{tag}</span>)}
        <span className="text-muted-sm">Updated <DateCell date={item!.updated_at} /></span>
        {item!.completed_at && <span className="text-muted-sm">Completed <DateCell date={item!.completed_at} /></span>}
      </div>
      <div className="card markdown-content"><ReactMarkdown>{item!.description || 'No description added.'}</ReactMarkdown></div>
    </>}
  </div>;
}
