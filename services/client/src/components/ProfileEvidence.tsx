import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigationType, useSearchParams } from 'react-router';
import { api, ApiError } from '../api';
import type { ClaimCorrectionInput, ParticipantProfile, ProfileClaim } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { safeHttpUrl } from '../utils/links';
import { Pagination } from './Pagination';
import { DateCell } from './table';
import { useDebouncedValue } from '../hooks/useDebouncedValue';

const CATEGORIES: [ProfileClaim['category'], string][] = [
  ['driver', 'Drivers'], ['priority', 'Priorities'], ['communication', 'Communication'],
  ['decision_pattern', 'Decision patterns'], ['perception', 'Perceptions'], ['interaction', 'Interactions'],
  ['uncertainty', 'Uncertainties'], ['strength', 'Strengths'], ['development_area', 'Development areas'],
  ['relationship', 'Relationship evidence'], ['role', 'Roles and organizations'],
];
const EPISTEMIC = { self_report: 'Self-reported', observed: 'Observed', inference: 'Hypothesis' };
const PAGE_SIZE = 20;

interface Edit {
  claimId: string; action: 'correct' | 'reject'; content: string; reason: string; revision: number; refreshAfter: number | null;
}

interface EvidenceItem extends ProfileClaim {
  profileRevision: number;
  readVersion: number;
}

export function ProfileEvidence({ profile, active, disabled, onBusyChange, onReload }: {
  profile: ParticipantProfile; active: boolean; disabled: boolean;
  onBusyChange: (busy: boolean) => void; onReload: () => void;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigationType = useNavigationType();
  const pendingSearch = useRef<URLSearchParams | null>(null);
  useEffect(() => {
    if (navigationType !== 'REPLACE' || pendingSearch.current?.toString() === searchParams.toString()) pendingSearch.current = null;
  }, [searchParams, navigationType]);
  const rawQuery = searchParams.get('q') || '';
  const [queryText, setQueryText] = useState(rawQuery);
  const debouncedQuery = useDebouncedValue(queryText.trim());
  const query = rawQuery.trim();
  const lastUrlQuery = useRef(rawQuery);
  const lastUrlSearch = useRef(searchParams.toString());
  const externalQuery = useRef<string | null>(null);
  useEffect(() => {
    const changed = lastUrlQuery.current !== rawQuery;
    const popped = navigationType === 'POP' && lastUrlSearch.current !== searchParams.toString();
    lastUrlQuery.current = rawQuery;
    lastUrlSearch.current = searchParams.toString();
    if (popped || (changed && navigationType !== 'REPLACE')) {
      externalQuery.current = rawQuery.trim();
      setQueryText(rawQuery);
    }
  }, [rawQuery, navigationType, searchParams]);
  const epistemic = (['observed', 'self_report', 'inference'] as const).find(value => value === searchParams.get('epistemic'));
  const category = CATEGORIES.find(([value]) => value === searchParams.get('category'))?.[0];
  const confidence = (['low', 'medium', 'high'] as const).find(value => value === searchParams.get('confidence'));
  const status = (['active', 'corrected', 'rejected'] as const).find(value => value === searchParams.get('status'));
  const targetId = searchParams.get('target_id') || undefined;
  const sort = searchParams.get('sort') === 'oldest' ? 'oldest' : 'newest';
  const criteriaPending = queryText.trim() !== query;
  const hasFilters = Boolean(queryText || epistemic || category || confidence || status || targetId);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const updateSearch = useCallback((update: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(pendingSearch.current ?? searchParams);
    update(next);
    pendingSearch.current = next;
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);
  useEffect(() => {
    if (externalQuery.current !== null) {
      if (debouncedQuery === externalQuery.current) externalQuery.current = null;
      return;
    }
    if (debouncedQuery !== queryText.trim() || debouncedQuery === query) return;
    updateSearch(next => { if (debouncedQuery) next.set('q', debouncedQuery); else next.delete('q'); });
  }, [debouncedQuery, queryText, query, updateSearch]);
  const setFilter = (key: string, value: string) => {
    setExpandedId(null);
    updateSearch(next => {
      if (value) next.set(key, value); else next.delete(key);
    });
  };
  const clearFilters = () => {
    externalQuery.current = null;
    setQueryText('');
    setExpandedId(null);
    updateSearch(next => {
      for (const key of ['q', 'epistemic', 'category', 'confidence', 'status', 'target_id']) next.delete(key);
    });
  };
  const [edit, setEdit] = useState<Edit | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const readVersion = useRef(0);
  const evidence = usePagination<EvidenceItem>(async (limit, offset) => {
    const version = ++readVersion.current;
    const page = await api.profiles.claims(profile.id, { limit, offset, sort, ...(query ? { q: query } : {}), ...(epistemic ? { epistemic } : {}), ...(category ? { category } : {}), ...(confidence ? { confidence } : {}), ...(status ? { status } : {}), ...(targetId ? { target_id: targetId } : {}) });
    if (page.profile_id !== profile.id) {
      onReload();
      throw new Error('Profile identity changed; reload the canonical profile.');
    }
    if (page.revision !== profile.revision) onReload();
    return { ...page, items: page.items.map(claim => ({ ...claim, profileRevision: page.revision, readVersion: version })) };
  }, [profile.id, query, epistemic, category, confidence, status, targetId, sort], PAGE_SIZE);
  const { refresh: refreshEvidence, loading, error, total, offset, setOffset } = evidence;
  const correction = useApiMutation({
    mutationFn: ({ claimId, body }: { claimId: string; body: ClaimCorrectionInput }) => api.profiles.correctClaim(profile.id, claimId, body),
    onSuccess: () => { setEdit(null); setNotice(null); onReload(); evidence.refresh({ showLoading: false }); },
    onError: failure => {
      if (failure instanceof ApiError && failure.status === 409) {
        const refreshAfter = readVersion.current;
        setNotice('This profile changed. Review the latest version and submit again.');
        setEdit(previous => previous && { ...previous, refreshAfter });
        onReload(); evidence.refresh({ showLoading: false });
      } else setNotice('Could not save the change. Your draft is retained.');
    },
  });
  const busy = Boolean(edit) || correction.loading;
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);
  const previousView = useRef({ active, revision: profile.revision });
  useEffect(() => {
    const previous = previousView.current;
    previousView.current = { active, revision: profile.revision };
    if (active && (!previous.active || previous.revision !== profile.revision)) refreshEvidence({ showLoading: false });
  }, [active, profile.revision, refreshEvidence]);
  usePolling(() => evidence.refresh({ showLoading: false }), { enabled: active && !busy && !disabled && !criteriaPending });
  useEffect(() => {
    if (!loading && !error && !busy && total > 0 && offset >= total) {
      setOffset(Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE);
    }
  }, [loading, error, total, offset, setOffset, busy]);

  const displayedEdit = edit ? evidence.items.find(claim => claim.id === edit.claimId) : undefined;
  const freshAfterConflict = !edit || edit.refreshAfter === null || Boolean(displayedEdit && displayedEdit.readVersion > edit.refreshAfter);
  const canSave = Boolean(displayedEdit) && freshAfterConflict && !loading && !error && !correction.loading;
  const cancel = () => { setEdit(null); setNotice(null); };
  const startEdit = (claim: EvidenceItem, action: Edit['action']) => {
    if (criteriaPending || loading) return;
    setExpandedId(claim.id);
    setNotice(null);
    setEdit({ claimId: claim.id, action, content: claim.correction?.content || claim.content, reason: '', revision: claim.profileRevision, refreshAfter: null });
  };
  const save = () => {
    if (!edit || !displayedEdit || !canSave) return;
    if (!edit.reason.trim()) { setNotice('A reason is required.'); return; }
    if (edit.action === 'correct' && !edit.content.trim()) { setNotice('Corrected content is required.'); return; }
    setNotice(null);
    correction.mutate({ claimId: edit.claimId, body: {
      expected_revision: edit.refreshAfter === null ? edit.revision : displayedEdit.profileRevision,
      action: edit.action, reason: edit.reason.trim(), ...(edit.action === 'correct' ? { content: edit.content.trim() } : {}),
    } });
  };
  const editor = edit && <div className="profile-claim-edit">
    {displayedEdit ? <>
      {edit.refreshAfter !== null && <p className="text-muted-sm" role="status">{freshAfterConflict && !error
        ? 'The current saved observation is shown above. Review it before saving your draft again.'
        : 'Reload the current observation before saving your draft again.'}</p>}
      {edit.action === 'correct' && <><label className="form-label" htmlFor="claim-content">Corrected claim</label>
        <textarea id="claim-content" className="input" disabled={correction.loading} rows={3} maxLength={2000} value={edit.content} onChange={event => setEdit({ ...edit, content: event.target.value })} /></>}
      <label className="form-label" htmlFor="claim-reason">Reason</label>
      <textarea id="claim-reason" className="input" disabled={correction.loading} rows={2} maxLength={2000} value={edit.reason} onChange={event => setEdit({ ...edit, reason: event.target.value })} />
    </> : <p>The observation is no longer on this page. Reload the evidence to review it, or cancel this draft.</p>}
    <div className="flex-wrap">
      <button className="btn" onClick={save} disabled={!canSave}>{correction.loading ? 'Saving...' : edit.action === 'correct' ? 'Save correction' : 'Confirm rejection'}</button>
      {!displayedEdit && <button className="btn" onClick={() => refreshEvidence({ showLoading: false })} disabled={correction.loading}>Reload evidence</button>}
      <button className="btn" onClick={cancel} disabled={correction.loading}>Cancel</button>
    </div>
  </div>;

  return <section aria-label="Evidence and observations" id="profile-evidence">
    <div className="sub-tabs evidence-kinds" role="group" aria-label="Observation kinds">
      {([['', 'All'], ['observed', 'Observed'], ['self_report', 'Self-reported'], ['inference', 'Hypotheses']] as const).map(([value, label]) => <button key={value} className={(epistemic || '') === value ? 'active' : ''} aria-pressed={(epistemic || '') === value} disabled={busy} onClick={() => setFilter('epistemic', value)}>{label}</button>)}
    </div>
    <div className="evidence-filters">
      <div><label className="form-label" htmlFor="evidence-query">Search observations</label><input id="evidence-query" className="input" maxLength={1000} placeholder="Search saved observations" value={queryText} disabled={busy} onChange={event => { externalQuery.current = null; setQueryText(event.target.value); setExpandedId(null); }} /></div>
      <div><label className="form-label" htmlFor="evidence-category">Category</label><select id="evidence-category" className="input" disabled={busy} value={category || ''} onChange={event => setFilter('category', event.target.value)}><option value="">All categories</option>{CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
      <div><label className="form-label" htmlFor="evidence-confidence">Confidence</label><select id="evidence-confidence" className="input" disabled={busy} value={confidence || ''} onChange={event => setFilter('confidence', event.target.value)}><option value="">Any confidence</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></div>
      <div><label className="form-label" htmlFor="evidence-status">Review status</label><select id="evidence-status" className="input" disabled={busy} value={status || ''} onChange={event => setFilter('status', event.target.value)}><option value="">All states</option><option value="active">Active</option><option value="corrected">Corrected</option><option value="rejected">Rejected</option></select></div>
      <div><label className="form-label" htmlFor="evidence-sort">Sort</label><select id="evidence-sort" className="input" disabled={busy} value={sort} onChange={event => setFilter('sort', event.target.value)}><option value="newest">Newest saved</option><option value="oldest">Oldest saved</option></select></div>
    </div>
    <div className="evidence-list-summary">
      <span className="text-muted-sm">{evidence.total} {evidence.total === 1 ? 'observation' : 'observations'}</span>
      {targetId && <span className="tag">About <Link className="text-link" to={`/profiles/${targetId}`}>related person</Link> <button className="inline-clear" aria-label="Clear related person filter" disabled={busy} onClick={() => setFilter('target_id', '')}>×</button></span>}
      {hasFilters && <button className="btn btn-sm" disabled={busy} onClick={clearFilters}>Clear filters</button>}
    </div>
    {notice && <p className="card" role="alert">{notice}</p>}
    {evidence.error && <div className="card" role="alert"><p>Could not refresh this evidence. Your current view and drafts are retained.</p><button className="btn" onClick={() => refreshEvidence({ showLoading: false })}>Retry evidence</button></div>}
    {edit && !displayedEdit && <section className="card" aria-label="Evidence draft recovery">{editor}</section>}
    {loading && <p className="text-muted-sm" role="status">Loading evidence...</p>}
    <div className="evidence-table" role="region" aria-label="Observation list" tabIndex={0} aria-busy={loading || criteriaPending}>
      <table className="table"><thead><tr><th>Observation</th><th>Type</th><th>Confidence</th><th>Review status</th><th>Source</th><th>Details</th></tr></thead><tbody>
        {evidence.items.map(claim => {
          const expanded = expandedId === claim.id || edit?.claimId === claim.id;
          const content = claim.status === 'corrected' ? claim.correction?.content || claim.content : claim.content;
          const sourceUrl = safeHttpUrl(claim.source_url);
          return <Fragment key={claim.id}>
            <tr className={expanded ? 'evidence-row-expanded' : undefined}>
              <td><span className="evidence-preview" style={{ textDecoration: claim.status === 'rejected' ? 'line-through' : undefined }}>{content}</span></td>
              <td>{CATEGORIES.find(([key]) => key === claim.category)?.[1]}<div className="text-muted-sm">{EPISTEMIC[claim.epistemic]}</div></td>
              <td>{claim.confidence}</td><td><span className="tag">{claim.status === 'corrected' ? 'Corrected by you' : claim.status === 'rejected' ? 'Rejected by you' : 'Active'}</span></td>
              <td><Link className="text-link" to={`/meetings/${claim.meeting_id}#meeting-transcript`}>{claim.meeting_title || 'Source meeting'}</Link>{claim.meeting_date && <DateCell date={claim.meeting_date} />}</td>
              <td><button className="btn btn-sm" aria-expanded={expanded} aria-controls={`observation-${claim.id}`} disabled={busy || criteriaPending || loading} onClick={() => setExpandedId(expanded ? null : claim.id)}>{expanded ? 'Close details' : 'View observation'}</button></td>
            </tr>
            {expanded && <tr><td colSpan={6} className="evidence-detail-cell"><section id={`observation-${claim.id}`} aria-label="Observation details" className="evidence-detail">
              <p style={{ whiteSpace: 'pre-wrap', textDecoration: claim.status === 'rejected' ? 'line-through' : undefined }}>{content}</p>
              {claim.target_id && <p className="text-muted-sm">About <Link className="text-link" to={`/profiles/${claim.target_id}`}>{claim.target_name || 'another participant'}</Link></p>}
              {claim.rationale && !claim.correction && <p className="text-muted-sm" style={{ whiteSpace: 'pre-wrap' }}>{claim.rationale}</p>}
              {claim.correction && <div className="text-muted-sm"><p>Reason: {claim.correction.reason}</p><details><summary>Original claim</summary><p style={{ whiteSpace: 'pre-wrap' }}>{claim.content}</p>{claim.rationale && <p style={{ whiteSpace: 'pre-wrap' }}>Original rationale: {claim.rationale}</p>}</details></div>}
              <details><summary>Source evidence</summary>{claim.evidence.map((entry, index) => <blockquote key={`${entry.segment_id}-${index}`}><p style={{ whiteSpace: 'pre-wrap' }}>{entry.quote}</p><cite className="text-muted-sm">Transcript {entry.segment_id}</cite></blockquote>)}
                <Link className="text-link" to={`/meetings/${claim.meeting_id}#meeting-transcript`}>View source meeting</Link>{sourceUrl && <> · <a className="text-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">Open original meeting</a></>}
              </details>
              {edit?.claimId === claim.id ? editor : <div className="flex-wrap"><button className="btn btn-sm" onClick={() => startEdit(claim, 'correct')} disabled={disabled || busy || criteriaPending || loading}>Correct claim</button><button className="btn btn-sm" onClick={() => startEdit(claim, 'reject')} disabled={disabled || busy || criteriaPending || loading}>Reject claim</button></div>}
            </section></td></tr>}
          </Fragment>;
        })}
        {!loading && !error && evidence.total === 0 && <tr><td colSpan={6} className="loading">{hasFilters ? 'No observations match these filters.' : 'No saved observations yet. They appear as linked meetings are processed.'}</td></tr>}
      </tbody></table>
    </div>
    <Pagination total={evidence.total} limit={PAGE_SIZE} offset={evidence.offset} onPageChange={value => { setExpandedId(null); setOffset(value); }} disabled={busy || disabled || loading || criteriaPending} />
  </section>;
}
