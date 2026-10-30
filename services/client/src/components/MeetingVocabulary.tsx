import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api, ApiError } from '../api';
import type { MeetingVocabulary as VocabularyTerm } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePagination } from '../hooks/usePagination';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { Pagination } from './Pagination';

type Draft = { term: string; definition: string; entry?: VocabularyTerm };
type Change = { action: 'save'; draft: Draft } | { action: 'remove'; entry: VocabularyTerm };

export function MeetingVocabulary() {
  const [search, setSearch] = useState('');
  const query = useDebouncedValue(search.trim());
  const list = usePagination<VocabularyTerm>((limit, offset) => api.meetings.vocabulary.list({ limit, offset, q: query }), [query]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [removing, setRemoving] = useState<VocabularyTerm | null>(null);
  const [conflictId, setConflictId] = useState<string | null>(null);
  const [conflictRead, setConflictRead] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const mounted = useRef(false);
  const latestRefresh = useRef(list.refresh);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { latestRefresh.current = list.refresh; }, [list.refresh]);
  const readCurrent = useCallback(async () => {
    if (!conflictId) return null;
    try { return { entry: await api.meetings.vocabulary.get(conflictId), epoch: conflictRead }; }
    catch (error) {
      if (error instanceof ApiError && error.status === 404) return { entry: null, epoch: conflictRead };
      throw error;
    }
  }, [conflictId, conflictRead]);
  const current = useApiRead(readCurrent);
  const conflicted = conflictId !== null && conflictId === draft?.entry?.id;
  const accepted = current.data?.epoch === conflictRead;
  const latest = accepted && current.data?.entry?.id === conflictId ? current.data.entry : null;
  const conflictBlocked = conflicted && (current.loading || Boolean(current.error) || !accepted || !latest);
  const lastOffset = list.total > 0 ? Math.floor((list.total - 1) / list.limit) * list.limit : 0;
  const clamping = !list.loading && !list.error && list.offset > lastOffset;
  const { setOffset } = list;
  useEffect(() => { if (clamping) setOffset(lastOffset); }, [clamping, lastOffset, setOffset]);
  const change = useApiMutation({
    mutationFn: async (value: Change) => {
      if (value.action === 'remove') await api.meetings.vocabulary.remove(value.entry.id, value.entry.revision);
      else {
        const { term, definition, entry } = value.draft;
        if (entry) await api.meetings.vocabulary.update(entry.id, { term, definition, expected_revision: entry.revision });
        else await api.meetings.vocabulary.create({ term, definition });
      }
    },
    onSuccess: () => {
      if (!mounted.current) return;
      setDraft(null); setRemoving(null); setNotice(null); setConflictId(null);
      latestRefresh.current();
    },
    onError: failure => {
      if (!mounted.current) return;
      if (failure instanceof ApiError && failure.status === 409) {
        if (removing) { setRemoving(null); setNotice('This term changed. Review it before deleting.'); }
        else if (draft?.entry) {
          setConflictId(draft.entry.id); setConflictRead(value => value + 1);
          setNotice('This term changed. Review the latest entry, then save again.');
        } else setNotice('This term already exists. Review the vocabulary below.');
        latestRefresh.current();
      } else setNotice('Could not update the vocabulary. Your draft is retained.');
    },
  });
  const busy = Boolean(draft || removing || change.loading);
  const start = (entry?: VocabularyTerm) => {
    setDraft({ term: entry?.term || '', definition: entry?.definition || '', entry });
    setConflictId(null); setNotice(null);
  };
  const cancel = () => { setDraft(null); setNotice(null); setConflictId(null); };
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (!draft || change.loading) return;
    if (!draft.term.trim()) { setNotice('A term is required.'); return; }
    if (conflictBlocked) return;
    change.mutate({ action: 'save', draft: { ...draft, term: draft.term.trim(), definition: draft.definition.trim(), entry: conflicted ? latest! : draft.entry } });
  };
  const loading = list.loading || clamping;
  return <section className="card" aria-label="Meeting vocabulary">
    <div className="page-header profiles-header">
      <h3 className="section-title">Vocabulary</h3>
      {!draft && <button className="btn btn-primary" disabled={busy || loading} onClick={() => start()}>Add term</button>}
    </div>
    <p className="text-muted-sm" style={{ marginTop: 12 }}>Terms and meanings that guide new meeting memories.</p>
    <div className="search-bar" style={{ marginTop: 16 }}>
      <label className="form-label" htmlFor="vocabulary-search">Search vocabulary</label>
      <input id="vocabulary-search" className="input" value={search} placeholder="Search terms or definitions..." onChange={event => { setSearch(event.target.value); setRemoving(null); }} />
    </div>
    {loading && <p role="status">Loading vocabulary...</p>}
    {list.error && <p role="alert">Could not load vocabulary. <button className="btn btn-sm" onClick={() => list.refresh()}>Retry</button></p>}
    {notice && <p role="alert">{notice}</p>}
    {draft && <form className="management-form" aria-label="Vocabulary term" onSubmit={save}>
      <div><label className="form-label" htmlFor="vocabulary-term">Term</label>
        <input className="input" id="vocabulary-term" maxLength={200} value={draft.term} onChange={event => setDraft({ ...draft, term: event.target.value })} disabled={change.loading} /></div>
      <div><label className="form-label" htmlFor="vocabulary-definition">Meaning / definition (optional)</label>
        <textarea className="input" id="vocabulary-definition" rows={3} maxLength={2000} value={draft.definition} onChange={event => setDraft({ ...draft, definition: event.target.value })} disabled={change.loading} /></div>
      {conflicted && latest && <p className="text-muted-sm">Latest saved: {latest.term} — {latest.definition || 'No definition'}</p>}
      {conflicted && !current.loading && accepted && !current.error && !latest && <p role="alert">This term was removed. Cancel to add a new entry.</p>}
      {conflicted && current.error && <p role="alert">Could not reload the current term. Your draft is retained. <button className="btn btn-sm" type="button" onClick={() => current.refresh()}>Retry term refresh</button></p>}
      <div className="flex-wrap"><button className="btn" type="submit" disabled={change.loading || conflictBlocked}>{change.loading ? 'Saving...' : 'Save term'}</button>
        <button className="btn" type="button" disabled={change.loading} onClick={cancel}>Cancel</button></div>
    </form>}
    {!loading && !list.error && list.total === 0 && <p className="text-muted-sm">{query ? 'No vocabulary terms match your search.' : 'No vocabulary terms yet.'}</p>}
    {!loading && !list.error && list.items.length > 0 && <div className="table-container" style={{ marginTop: 16 }}>
      <table className="table vocabulary-table" aria-label="Vocabulary terms"><thead><tr><th className="vocabulary-term-cell">Term</th><th>Definition</th><th className="vocabulary-actions-cell">Actions</th></tr></thead>
        <tbody>{list.items.map(entry => <tr key={entry.id}>
          <td><strong className="vocabulary-preview" title={entry.term}>{entry.term}</strong></td>
          <td><span className="vocabulary-preview" title={entry.definition}>{entry.definition || '—'}</span></td>
          <td><div className="vocabulary-actions">{removing?.id === entry.id ? <>
            <button className="btn btn-danger btn-sm" aria-label="Confirm delete" disabled={change.loading} onClick={() => change.mutate({ action: 'remove', entry: removing })}>Delete?</button>
            <button className="btn btn-sm" aria-label="Cancel delete" disabled={change.loading} onClick={() => setRemoving(null)}>Cancel</button>
          </> : <>
            <button className="btn btn-sm" aria-label={`Edit ${entry.term}`} disabled={busy} onClick={() => start(entry)}>Edit</button>
            <button className="btn btn-danger btn-sm" aria-label={`Delete ${entry.term}`} disabled={busy} onClick={() => { setRemoving(entry); setNotice(null); }}>Delete</button>
          </>}</div></td>
        </tr>)}</tbody>
      </table>
    </div>}
    {!list.error && !clamping && <Pagination total={list.total} limit={list.limit} offset={list.offset} disabled={loading || Boolean(removing)}
      onPageChange={offset => { setRemoving(null); list.setOffset(offset); }} onLimitChange={value => { setRemoving(null); list.setLimit(value); list.setOffset(0); }} />}
  </section>;
}
