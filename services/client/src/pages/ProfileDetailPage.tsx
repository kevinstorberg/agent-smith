import { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { api, ApiError } from '../api';
import type { ClaimCorrectionInput, ProfileClaim } from '../api';
import { DateCell } from '../components/table';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePolling } from '../hooks/usePolling';
import { safeHttpUrl } from '../utils/links';

const CATEGORIES: [ProfileClaim['category'], string][] = [
  ['driver', 'Drivers'], ['priority', 'Priorities'], ['communication', 'Communication'],
  ['decision_pattern', 'Decision patterns'], ['perception', 'Perceptions'], ['interaction', 'Interactions'], ['uncertainty', 'Uncertainties'],
];
const EPISTEMIC = { self_report: 'Self-reported', observed: 'Observed', inference: 'Hypothesis' };

interface Edit {
  claimId: string;
  action: 'correct' | 'reject';
  content: string;
  reason: string;
  revision: number;
  conflicted: boolean;
}

export function ProfileDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const read = useCallback(() => id ? api.meetings.profile(id) : Promise.reject(new Error('Profile not found')), [id]);
  const { data: profile, loading, error, refresh } = useApiRead(read);
  const [edit, setEdit] = useState<Edit | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const failedChange = (failure: Error) => {
    if (failure instanceof ApiError && failure.status === 409) {
      setNotice('This profile changed. Review the latest version and submit again.');
      setEdit(previous => previous && { ...previous, conflicted: true });
      refresh();
    } else {
      setNotice('Could not save the change. Try again.');
    }
  };
  const correction = useApiMutation({
    mutationFn: ({ claimId, body }: { claimId: string; body: ClaimCorrectionInput }) => api.meetings.correctClaim(id!, claimId, body),
    onSuccess: () => { setEdit(null); setNotice(null); refresh(); },
    onError: failedChange,
  });
  const deletion = useApiMutation({
    mutationFn: (revision: number) => api.meetings.deleteProfile(id!, revision),
    onSuccess: () => navigate('/meetings'),
    onError: failedChange,
  });
  usePolling(() => refresh({ showLoading: false }), { enabled: !edit && !correction.loading && !deletion.loading });

  const startEdit = (claim: ProfileClaim, action: Edit['action']) => {
    if (!profile) return;
    setNotice(null);
    setEdit({ claimId: claim.id, action, content: claim.correction?.content || claim.content, reason: '', revision: profile.revision, conflicted: false });
  };
  const save = () => {
    if (!edit || !profile) return;
    if (!edit.reason.trim()) { setNotice('A reason is required.'); return; }
    if (edit.action === 'correct' && !edit.content.trim()) { setNotice('Corrected content is required.'); return; }
    setNotice(null);
    correction.mutate({ claimId: edit.claimId, body: {
      expected_revision: edit.conflicted ? profile.revision : edit.revision,
      action: edit.action, reason: edit.reason.trim(), ...(edit.action === 'correct' ? { content: edit.content.trim() } : {}),
    } });
  };
  const remove = () => {
    if (profile && confirm('Delete this participant profile? It will stay deleted and will not be recreated automatically.')) {
      deletion.mutate(profile.revision);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">{loading || error ? 'Participant profile' : profile?.display_name}</h2>
        <Link className="btn" to="/meetings">Back to meetings</Link>
      </div>
      {loading ? <div className="loading">Loading participant profile...</div> : error ? (
        <div className="card" role="alert"><p>Could not load this participant profile. It may be unavailable or deleted.</p><button className="btn" onClick={() => refresh()}>Retry</button></div>
      ) : profile && (
        <>
          <div className="card">
            {profile.email && <p>{profile.email}</p>}
            <p className="text-muted-sm">{profile.identity_scope === 'email' ? 'Identity linked by email.' : 'Identified in this meeting only; no cross-meeting identity match.'}</p>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
              <span className="tag">Revision {profile.revision}</span><DateCell date={profile.updated_at} />
              <button className="btn btn-danger" style={{ marginLeft: 'auto' }} onClick={remove} disabled={Boolean(edit) || correction.loading || deletion.loading}>
                {deletion.loading ? 'Deleting...' : 'Delete profile'}
              </button>
            </div>
          </div>
          {notice && <p className="card" role="alert">{notice}</p>}
          {profile.claims.length === 0 && <p className="card text-muted-sm">No claims with available source meetings.</p>}
          {CATEGORIES.map(([category, label]) => {
            const claims = profile.claims.filter(claim => claim.category === category);
            return claims.length === 0 ? null : <section key={category} aria-label={label}>
              <h3 className="section-title">{label}</h3>
              {claims.map(claim => {
                const sourceUrl = safeHttpUrl(claim.source_url);
                return <article className="card" key={claim.id}>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <span className="tag">{EPISTEMIC[claim.epistemic]}</span>
                    <span className="tag">{claim.confidence} confidence</span>
                    {claim.status !== 'active' && <span className="tag">{claim.status === 'corrected' ? 'Corrected by you' : 'Rejected by you'}</span>}
                  </div>
                  {claim.target_id && <p className="text-muted-sm">About {claim.target_name || 'another participant'}</p>}
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
                    {claim.evidence.map((evidence, index) => <blockquote key={`${evidence.segment_id}-${index}`}>
                      <p style={{ whiteSpace: 'pre-wrap' }}>{evidence.quote}</p><cite className="text-muted-sm">Transcript {evidence.segment_id}</cite>
                    </blockquote>)}
                    <Link to={`/meetings/${claim.meeting_id}#meeting-transcript`}>View source meeting</Link>
                    {sourceUrl && <> · <a href={sourceUrl} target="_blank" rel="noopener noreferrer">Open original meeting</a></>}
                  </details>
                  {edit?.claimId === claim.id ? <div style={{ marginTop: 12 }}>
                    {edit.action === 'correct' && <><label className="form-label" htmlFor="claim-content">Corrected claim</label>
                      <textarea id="claim-content" className="input" style={{ width: '100%', minHeight: 80 }} maxLength={2000} value={edit.content} onChange={event => setEdit({ ...edit, content: event.target.value })} /></>}
                    <label className="form-label" htmlFor="claim-reason">Reason</label>
                    <textarea id="claim-reason" className="input" style={{ width: '100%', minHeight: 60 }} maxLength={2000} value={edit.reason} onChange={event => setEdit({ ...edit, reason: event.target.value })} />
                    <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                      <button className="btn btn-primary" onClick={save} disabled={correction.loading || loading}>{correction.loading ? 'Saving...' : edit.action === 'correct' ? 'Save correction' : 'Confirm rejection'}</button>
                      <button className="btn" onClick={() => { setEdit(null); setNotice(null); }} disabled={correction.loading}>Cancel</button>
                    </div>
                  </div> : <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                    <button className="btn btn-sm" onClick={() => startEdit(claim, 'correct')} disabled={Boolean(edit) || deletion.loading}>Correct claim</button>
                    <button className="btn btn-sm" onClick={() => startEdit(claim, 'reject')} disabled={Boolean(edit) || deletion.loading}>Reject claim</button>
                  </div>}
                </article>;
              })}
            </section>;
          })}
        </>
      )}
    </div>
  );
}
