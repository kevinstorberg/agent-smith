import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { ClaimCorrectionInput, ParticipantProfile, ProfileClaim } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { safeHttpUrl } from '../utils/links';
import { Pagination } from './Pagination';

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
  const [edit, setEdit] = useState<Edit | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const readVersion = useRef(0);
  const evidence = usePagination<EvidenceItem>(async (limit, offset) => {
    const version = ++readVersion.current;
    const page = await api.profiles.claims(profile.id, { limit, offset });
    if (page.profile_id !== profile.id) {
      onReload();
      throw new Error('Profile identity changed; reload the canonical profile.');
    }
    if (page.revision !== profile.revision) onReload();
    return { ...page, items: page.items.map(claim => ({ ...claim, profileRevision: page.revision, readVersion: version })) };
  }, [profile.id], PAGE_SIZE);
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
  usePolling(() => evidence.refresh({ showLoading: false }), { enabled: active && !busy && !disabled });
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
    <p className="text-muted-sm profile-evidence-intro">Saved observations and their source meetings. Showing up to 20 observations per page.</p>
    {notice && <p className="card" role="alert">{notice}</p>}
    {evidence.error && <div className="card" role="alert"><p>Could not refresh this evidence. Your current view and drafts are retained.</p>
      <button className="btn" onClick={() => evidence.refresh({ showLoading: false })}>Retry evidence</button></div>}
    {edit && !displayedEdit && <section className="card" aria-label="Evidence draft recovery">{editor}</section>}
    {evidence.loading ? <div className="loading">Loading evidence...</div> : <>
      {!evidence.error && evidence.total === 0 && <p className="card text-muted-sm">No saved observations yet. They appear as linked meetings are processed.</p>}
      {CATEGORIES.map(([category, label]) => {
        const claims = evidence.items.filter(claim => claim.category === category);
        return claims.length === 0 ? null : <section key={category} aria-label={label}>
          <h3 className="section-title">{label}</h3>
          {claims.map(claim => {
            const sourceUrl = safeHttpUrl(claim.source_url);
            return <article className="card" key={claim.id}>
              <div className="flex-wrap">
                <span className="tag">{EPISTEMIC[claim.epistemic]}</span><span className="tag">{claim.confidence} confidence</span>
                {claim.status !== 'active' && <span className="tag">{claim.status === 'rejected' ? 'Rejected by you' : 'Corrected by you'}</span>}
              </div>
              {claim.target_id && <p className="text-muted-sm">About <Link className="text-link" to={`/profiles/${claim.target_id}`}>{claim.target_name || 'another participant'}</Link></p>}
              <p style={{ whiteSpace: 'pre-wrap', marginTop: 8, textDecoration: claim.status === 'rejected' ? 'line-through' : undefined }}>
                {claim.status === 'corrected' ? claim.correction?.content || claim.content : claim.content}
              </p>
              {claim.rationale && !claim.correction && <p className="text-muted-sm" style={{ whiteSpace: 'pre-wrap' }}>{claim.rationale}</p>}
              {claim.correction && <div className="text-muted-sm" style={{ marginTop: 8 }}>
                <p>Reason: {claim.correction.reason}</p>
                <details><summary>Original claim</summary><p style={{ whiteSpace: 'pre-wrap' }}>{claim.content}</p>
                  {claim.rationale && <p style={{ whiteSpace: 'pre-wrap' }}>Original rationale: {claim.rationale}</p>}
                </details>
              </div>}
              <details style={{ marginTop: 8 }}><summary>Source evidence</summary>
                {claim.evidence.map((entry, index) => <blockquote key={`${entry.segment_id}-${index}`}>
                  <p style={{ whiteSpace: 'pre-wrap' }}>{entry.quote}</p><cite className="text-muted-sm">Transcript {entry.segment_id}</cite>
                </blockquote>)}
                <Link className="text-link" to={`/meetings/${claim.meeting_id}#meeting-transcript`}>View source meeting</Link>
                {sourceUrl && <> · <a className="text-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">Open original meeting</a></>}
              </details>
              {edit?.claimId === claim.id ? editor : <div className="flex-wrap" style={{ marginTop: 12 }}>
                <button className="btn btn-sm" onClick={() => startEdit(claim, 'correct')} disabled={disabled || busy}>Correct claim</button>
                <button className="btn btn-sm" onClick={() => startEdit(claim, 'reject')} disabled={disabled || busy}>Reject claim</button>
              </div>}
            </article>;
          })}
        </section>;
      })}
      <Pagination total={evidence.total} limit={PAGE_SIZE} offset={evidence.offset} onPageChange={evidence.setOffset} disabled={busy || disabled} />
    </>}
  </section>;
}
