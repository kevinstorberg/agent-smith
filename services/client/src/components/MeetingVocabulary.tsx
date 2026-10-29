import { useCallback, useState } from 'react';
import type { FormEvent } from 'react';
import { api, ApiError } from '../api';
import type { MeetingVocabulary as VocabularyTerm } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';

type Draft = { term: string; definition: string; entry?: VocabularyTerm };
type Change = { action: 'save'; draft: Draft } | { action: 'remove'; entry: VocabularyTerm };

export function MeetingVocabulary() {
  const read = useCallback(() => api.meetings.vocabulary.list(), []);
  const { data, loading, error, refresh } = useApiRead(read);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [removing, setRemoving] = useState<VocabularyTerm | null>(null);
  const [conflicted, setConflicted] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const latest = data?.items.find(item => item.id === draft?.entry?.id);
  const change = useApiMutation({
    mutationFn: async (value: Change) => {
      if (value.action === 'remove') {
        await api.meetings.vocabulary.remove(value.entry.id, value.entry.revision);
      } else {
        const { term, definition, entry } = value.draft;
        if (entry) await api.meetings.vocabulary.update(entry.id, { term, definition, expected_revision: entry.revision });
        else await api.meetings.vocabulary.create({ term, definition });
      }
    },
    onSuccess: () => { setDraft(null); setRemoving(null); setNotice(null); refresh(); },
    onError: failure => {
      if (failure instanceof ApiError && failure.status === 409) {
        if (removing) {
          setRemoving(null);
          setNotice('This term changed. Review it before deleting.');
        } else if (draft?.entry) {
          setConflicted(true);
          setNotice('This term changed. Review the latest entry, then save again.');
        } else setNotice('This term already exists. Review the vocabulary below.');
        refresh();
      } else setNotice('Could not update the vocabulary. Try again.');
    },
  });
  const busy = Boolean(draft || removing || change.loading);
  const start = (entry?: VocabularyTerm) => {
    setDraft({ term: entry?.term || '', definition: entry?.definition || '', entry });
    setConflicted(false); setNotice(null);
  };
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    if (!draft.term.trim()) { setNotice('A term is required.'); return; }
    if (conflicted && (loading || error || !latest)) {
      setNotice('Reload the vocabulary and review the latest entry before saving.'); return;
    }
    change.mutate({ action: 'save', draft: {
      ...draft, term: draft.term.trim(), definition: draft.definition.trim(),
      entry: conflicted ? latest : draft.entry,
    } });
  };

  return <section className="card" aria-label="Meeting vocabulary">
    <div className="page-header profiles-header">
      <h3 className="section-title">Vocabulary</h3>
      {!draft && <button className="btn btn-primary" disabled={busy || loading} onClick={() => start()}>Add term</button>}
    </div>
    <p className="text-muted-sm" style={{ marginTop: 12 }}>Terms and meanings that guide new meeting memories.</p>
    {loading && <p role="status">Loading vocabulary...</p>}
    {error && <p role="alert">Could not load vocabulary. <button className="btn btn-sm" onClick={() => refresh()}>Retry</button></p>}
    {notice && <p role="alert">{notice}</p>}
    {draft ? <form className="management-form" aria-label="Vocabulary term" onSubmit={save}>
      <div>
        <label className="form-label" htmlFor="vocabulary-term">Term</label>
        <input className="input" id="vocabulary-term" maxLength={200} value={draft.term} onChange={event => setDraft({ ...draft, term: event.target.value })} disabled={change.loading} />
      </div>
      <div>
        <label className="form-label" htmlFor="vocabulary-definition">Meaning / definition (optional)</label>
        <textarea className="input" id="vocabulary-definition" rows={3} maxLength={2000} value={draft.definition} onChange={event => setDraft({ ...draft, definition: event.target.value })} disabled={change.loading} />
      </div>
      {conflicted && latest && <p className="text-muted-sm">Latest saved: {latest.term} — {latest.definition || 'No definition'}</p>}
      {conflicted && !loading && !error && !latest && <p role="alert">This term was removed. Cancel to add a new entry.</p>}
      <div className="flex-wrap" style={{ display: 'flex', gap: 8 }}>
        <button className="btn" type="submit" disabled={change.loading || Boolean(conflicted && (loading || error || !latest))}>{change.loading ? 'Saving...' : 'Save term'}</button>
        <button className="btn" type="button" disabled={change.loading} onClick={() => { setDraft(null); setNotice(null); }}>Cancel</button>
      </div>
    </form> : null}
    {!loading && !error && !data?.items.length && <p className="text-muted-sm">No vocabulary terms yet.</p>}
    <ul className="management-list">
      {data?.items.map(entry => <li key={entry.id} className="management-row">
        <strong>{entry.term}</strong>
        {entry.definition && <p style={{ whiteSpace: 'pre-wrap' }}>{entry.definition}</p>}
        {removing?.id === entry.id ? <div className="flex-wrap" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span>Delete this term?</span>
          <button className="btn btn-danger btn-sm" disabled={change.loading} onClick={() => change.mutate({ action: 'remove', entry: removing })}>Confirm delete</button>
          <button className="btn btn-sm" disabled={change.loading} onClick={() => setRemoving(null)}>Cancel delete</button>
        </div> : <div className="flex-wrap" style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-sm" aria-label={`Edit ${entry.term}`} disabled={busy} onClick={() => start(entry)}>Edit</button>
          <button className="btn btn-danger btn-sm" aria-label={`Delete ${entry.term}`} disabled={busy} onClick={() => { setRemoving(entry); setNotice(null); }}>Delete</button>
        </div>}
      </li>)}
    </ul>
  </section>;
}
