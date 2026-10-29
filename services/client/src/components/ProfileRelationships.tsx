import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { ParticipantProfile, ProfileRelationship, ProfileSummary } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { ProfilePicker } from './ProfilePicker';

interface Draft { edge: ProfileRelationship | null; target: ProfileSummary | null; label: string; notes: string; revision: number; conflicted: boolean }

export function ProfileRelationships({ profile, disabled, onBusyChange, onReload }: {
  profile: ParticipantProfile; disabled: boolean; onBusyChange: (busy: boolean) => void; onReload: () => void;
}) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [targets, setTargets] = useState<ProfileSummary[]>([]);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const failed = (failure: Error) => {
    if (failure instanceof ApiError && failure.status === 409) {
      setDraft(previous => previous && { ...previous, conflicted: true }); setRefreshVersion(value => value + 1);
      setNotice('This relationship or profile changed. Review the refreshed information and save again.'); onReload();
    } else setNotice('Could not save this relationship. Check the fields and try again.');
  };
  const saved = () => { setDraft(null); setNotice(null); onReload(); };
  const save = useApiMutation({
    mutationFn: () => {
      const edit = draft!;
      if (edit.edge) return api.profiles.updateRelationship(profile.id, edit.edge.id, {
        expected_revision: edit.conflicted ? profile.relationships?.find(edge => edge.id === edit.edge!.id)?.revision ?? edit.edge.revision : edit.edge.revision,
        label: edit.label.trim(), notes: edit.notes.trim(),
      });
      return api.profiles.createRelationship(profile.id, { expected_revision: edit.conflicted ? profile.revision : edit.revision,
        target_id: edit.target!.id, target_revision: edit.conflicted ? targets.find(target => target.id === edit.target!.id)?.revision ?? edit.target!.revision : edit.target!.revision,
        label: edit.label.trim(), notes: edit.notes.trim(),
      });
    }, onSuccess: saved, onError: failed,
  });
  const remove = useApiMutation({
    mutationFn: (edge: ProfileRelationship) => api.profiles.removeRelationship(profile.id, edge.id, edge.revision), onSuccess: saved, onError: failed,
  });
  const busy = Boolean(draft) || save.loading || remove.loading;
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);
  return <section className="card" aria-label="Profile relationships">
    <div className="page-header profiles-header"><h3 className="section-title">Relationships</h3>
      <button className="btn" disabled={disabled || busy} onClick={() => { setNotice(null); setDraft({ edge: null, target: null, label: '', notes: '', revision: profile.revision, conflicted: false }); }}>Add relationship</button>
    </div>
    {!profile.relationships?.some(edge => !edge.dismissed) && <p className="text-muted-sm">No relationships saved. Add someone you know, or review evidence from future persona analysis.</p>}
    {profile.relationships?.filter(edge => !edge.dismissed).map(edge => <article key={edge.id} className="relationship-row">
      <p><Link className="text-link" to={`/profiles/${edge.subject_id}`}>{edge.subject_name}</Link> → <Link className="text-link" to={`/profiles/${edge.target_id}`}>{edge.target_name}</Link></p>
      <p>{edge.label || 'Relationship'}</p><p className="text-muted-sm" style={{ whiteSpace: 'pre-wrap' }}>{edge.notes}</p>
      {edge.claims.length > 0 && <details><summary>Meeting evidence ({edge.claims.length})</summary>
        {edge.claims.map(claim => <div key={claim.id} style={{ marginTop: 8 }}>
          {claim.status !== 'active' && <span className="tag tag-sm">{claim.status === 'rejected' ? 'Rejected by you' : 'Corrected by you'}</span>}
          <p style={{ textDecoration: claim.status === 'rejected' ? 'line-through' : undefined }}>{claim.status === 'corrected' ? claim.correction?.content || claim.content : claim.content}</p>
          {claim.correction?.reason && <p className="text-muted-sm">Reason: {claim.correction.reason}</p>}
          <Link className="text-link" to={`/meetings/${claim.meeting_id}#meeting-transcript`}>Source meeting</Link>
        </div>)}
      </details>}
      <div className="flex-wrap" style={{ marginTop: 8 }}>
        <button className="btn btn-sm" disabled={disabled || busy} onClick={() => { setNotice(null); setDraft({ edge, target: null, label: edge.label, notes: edge.notes, revision: profile.revision, conflicted: false }); }}>Edit relationship</button>
        <button className="btn btn-sm btn-danger" disabled={disabled || busy} onClick={() => { if (confirm(`Remove the relationship from ${edge.subject_name} to ${edge.target_name}?`)) remove.mutate(edge); }}>Remove relationship</button>
      </div>
    </article>)}
    {draft && <form className="participant-form" onSubmit={event => { event.preventDefault(); if (save.loading) return; if (!draft.edge && !draft.target) { setNotice('Select the other profile.'); return; } save.mutate(); }}>
      {draft.edge ? <p>Editing {draft.edge.subject_name} → {draft.edge.target_name}</p> : <>
        <p>Relationship from {profile.display_name} to the selected person.</p>
        <ProfilePicker label="Find related person" selectionLabel="Related profile" value={draft.target?.id || ''} onSelect={target => setDraft({ ...draft, target })}
          excludeId={profile.id} disabled={save.loading} refreshVersion={refreshVersion} onResults={setTargets} selectedLabel={draft.target?.display_name} />
      </>}
      <div><label className="form-label" htmlFor="relationship-label">Relationship label</label>
        <input id="relationship-label" className="input" disabled={save.loading} maxLength={200} value={draft.label} placeholder="e.g. reports to" onChange={event => setDraft({ ...draft, label: event.target.value })} /></div>
      <div><label className="form-label" htmlFor="relationship-notes">Your relationship notes</label>
        <textarea id="relationship-notes" className="input" disabled={save.loading} rows={3} maxLength={4000} value={draft.notes} onChange={event => setDraft({ ...draft, notes: event.target.value })} /></div>
      <div className="flex-wrap"><button className="btn" disabled={save.loading}>{save.loading ? 'Saving...' : 'Save relationship'}</button>
        <button className="btn" type="button" disabled={save.loading} onClick={() => { setDraft(null); setNotice(null); }}>Cancel</button></div>
    </form>}
    {notice && <p role="alert">{notice}</p>}
  </section>;
}
