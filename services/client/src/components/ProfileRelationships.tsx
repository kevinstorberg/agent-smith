import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { ParticipantProfile, ProfileRelationship, ProfileSummary } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { formatProfileCoverage } from '../utils/profileFields';
import { ProfilePicker } from './ProfilePicker';
import { ProfileNotes } from './ProfileNotes';

interface Draft {
  edge: ProfileRelationship | null; target: ProfileSummary | null; label: string; notes: string;
  notesChanged: boolean; revision: number; refreshAfter: ParticipantProfile | null;
}

export function ProfileRelationships({ profile, disabled, onBusyChange, onReload }: {
  profile: ParticipantProfile; disabled: boolean; onBusyChange: (busy: boolean) => void; onReload: () => void;
}) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [targets, setTargets] = useState<ProfileSummary[]>([]);
  const [contextBusy, setContextBusy] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const latestProfile = useRef(profile);
  useEffect(() => { latestProfile.current = profile; }, [profile]);
  const legacyProof = profile.section_evidence?.relationships;
  const legacyProtected = legacyProof ? legacyProof.human === true : Object.hasOwn(profile.section_notes || {}, 'relationships');
  const edges = (profile.relationships || []).filter(edge => !edge.dismissed);
  const hasSavedContext = profile.section_notes?.relationships !== undefined || legacyProtected || contextBusy;
  const hasContextText = Boolean(profile.section_notes?.relationships);
  const hasPersonAnalysis = edges.some(edge => Boolean(edge.notes) || edge.analysis_evidence?.human === true
    || edge.analysis_evidence?.origin === 'human' || Boolean(edge.analysis_evidence?.generated_at));
  const currentEdge = draft?.edge ? edges.find(edge => edge.id === draft.edge!.id) : undefined;
  const failed = (failure: Error) => {
    if (failure instanceof ApiError && failure.status === 409) {
      const refreshedAfter = latestProfile.current;
      setDraft(previous => previous && { ...previous, refreshAfter: refreshedAfter });
      setRefreshVersion(value => value + 1);
      setNotice('This relationship or profile changed. Review the refreshed information and save again.'); onReload();
    } else setNotice('Could not save this relationship. Your draft is retained.');
  };
  const saved = () => { setDraft(null); setNotice(null); onReload(); };
  const save = useApiMutation({
    mutationFn: () => {
      const edit = draft!;
      const notes = edit.notesChanged ? { notes: edit.notes.trim() } : {};
      if (edit.edge) return api.profiles.updateRelationship(profile.id, edit.edge.id, {
        expected_revision: edit.refreshAfter === null ? edit.edge.revision : currentEdge!.revision,
        label: edit.label.trim(), ...notes,
      });
      return api.profiles.createRelationship(profile.id, {
        expected_revision: edit.refreshAfter === null ? edit.revision : profile.revision,
        target_id: edit.target!.id,
        target_revision: edit.refreshAfter === null ? edit.target!.revision : targets.find(target => target.id === edit.target!.id)?.revision ?? edit.target!.revision,
        label: edit.label.trim(), ...notes,
      });
    }, onSuccess: saved, onError: failed,
  });
  const remove = useApiMutation({ mutationFn: (edge: ProfileRelationship) => api.profiles.removeRelationship(profile.id, edge.id, edge.revision), onSuccess: saved, onError: failed });
  const release = useApiMutation({ mutationFn: (edge: ProfileRelationship) => api.profiles.updateRelationship(profile.id, edge.id, { expected_revision: edge.revision, allow_agent_notes: true }), onSuccess: saved, onError: failed });
  const saving = save.loading || remove.loading || release.loading;
  const busy = Boolean(draft) || saving || contextBusy;
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);
  const canSave = !saving && (!draft?.edge || Boolean(currentEdge && (draft.refreshAfter === null || profile !== draft.refreshAfter)));
  const editor = draft && <form className="participant-form" onSubmit={event => {
    event.preventDefault(); if (!canSave) return;
    if (!draft.edge && !draft.target) { setNotice('Select the other profile.'); return; }
    save.mutate();
  }}>
    {draft.edge ? currentEdge ? <p>Editing {currentEdge.subject_name} → {currentEdge.target_name}</p>
      : <p>This relationship is no longer available. Reload the profile or cancel this draft.</p> : <>
      <p>Relationship from {profile.display_name} to the selected person.</p>
      <ProfilePicker label="Find related person" selectionLabel="Related profile" value={draft.target?.id || ''} onSelect={target => setDraft({ ...draft, target })}
        excludeId={profile.id} disabled={saving} refreshVersion={refreshVersion} onResults={setTargets} selectedLabel={draft.target?.display_name} />
    </>}
    {(!draft.edge || currentEdge) && <>
      {draft.refreshAfter !== null && currentEdge && <details><summary>Current saved assessment</summary><p style={{ whiteSpace: 'pre-wrap' }}>{currentEdge.notes || 'Empty'}</p></details>}
      <div><label className="form-label" htmlFor="relationship-label">Relationship label</label>
        <input id="relationship-label" className="input" disabled={saving} maxLength={200} value={draft.label} placeholder="e.g. reports to" onChange={event => setDraft({ ...draft, label: event.target.value })} /></div>
      <div><label className="form-label" htmlFor="relationship-notes">Relationship assessment</label>
        <textarea id="relationship-notes" className="input" disabled={saving} rows={5} maxLength={4000} value={draft.notes} onChange={event => setDraft({ ...draft, notes: event.target.value, notesChanged: true })} /></div>
      <p className="text-muted-sm">Your assessment edits, including an empty assessment, are protected from automatic updates. Changing only the label keeps the current assessment ownership.</p>
    </>}
    <div className="flex-wrap"><button className="btn" disabled={!canSave}>{save.loading ? 'Saving...' : 'Save relationship'}</button>
      <button className="btn" type="button" disabled={saving} onClick={() => { setDraft(null); setNotice(null); }}>Cancel</button></div>
  </form>;
  const groups = new Map<string, { id: string; name: string; edges: ProfileRelationship[] }>();
  for (const edge of edges) {
    const outgoing = edge.subject_id === profile.id;
    const id = outgoing ? edge.target_id : edge.subject_id;
    const group = groups.get(id) || { id, name: outgoing ? edge.target_name : edge.subject_name, edges: [] };
    group.edges.push(edge); groups.set(id, group);
  }
  return <section aria-label="Profile relationships">
    <div className="page-header profiles-header"><h3 className="section-title">Relationships</h3>
      <button className="btn" disabled={disabled || busy} onClick={() => { setNotice(null); setDraft({ edge: null, target: null, label: '', notes: '', notesChanged: false, revision: profile.revision, refreshAfter: null }); }}>Add relationship</button>
    </div>
    {notice && <p className="card" role="alert">{notice}</p>}
    {hasSavedContext && <details className="profile-legacy-assessment" open={!hasPersonAnalysis || contextBusy} aria-label="Saved relationship context">
      <summary>Saved relationship context</summary>
      <p className="text-muted-sm">{hasPersonAnalysis ? 'Earlier relationship context remains available for reference. Individual relationships below contain the latest updates.' : 'Saved relationship analysis remains available as individual relationships are updated. Your edits stay protected.'}</p>
      <ProfileNotes profile={profile} sectionKeys={['relationships']} embedded disabled={disabled || Boolean(draft) || saving}
        onBusyChange={setContextBusy} onReload={onReload} />
    </details>}
    {draft && !draft.edge && <div className="card">{editor}</div>}
    {draft?.edge && !currentEdge && <section className="card" aria-label="Relationship draft recovery">{editor}</section>}
    {groups.size === 0 && <p className="card text-muted-sm">{hasContextText ? 'No linked profiles yet. Add a relationship to connect a person to this profile.' : 'No relationships saved. Add someone you know, or refresh the assessment after meeting observations are available.'}</p>}
    {[...groups.values()].sort((first, second) => first.name.localeCompare(second.name) || first.id.localeCompare(second.id)).map(group => <article key={group.id} className="card relationship-person" aria-label={`Relationship with ${group.name}`}>
      <h4 className="relationship-person-name"><Link className="text-link" to={`/profiles/${group.id}`}>{group.name}</Link></h4>
      {group.edges.map(edge => {
        const proof = edge.analysis_evidence;
        const count = edge.claim_count ?? edge.claims.length;
        return <section className="relationship-perspective" key={edge.id} aria-label={`${edge.subject_name} to ${edge.target_name} relationship`}>
          <h5>{edge.subject_name} → {edge.target_name}</h5>
          {edge.label && <p className="text-muted-sm relationship-label">{edge.label}</p>}
          {draft?.edge?.id === edge.id ? editor : <>
            {edge.notes ? <div className="markdown-content"><ReactMarkdown>{edge.notes}</ReactMarkdown></div>
              : proof?.human ? <p className="text-muted-sm">You have kept this assessment empty.</p>
                : (!hasContextText || proof?.generated_at || proof?.status === 'stale') && <p className="text-muted-sm">{proof?.status === 'stale' ? 'This relationship assessment needs a refresh.' : proof?.generated_at ? 'There is not enough saved evidence to assess this relationship yet.' : 'This relationship assessment has not been generated yet.'}</p>}
            <div className="flex-wrap relationship-evidence">
              {proof?.human ? <span className="tag">Edited by you</span> : proof && (proof.origin === 'human' || proof.generated_at || proof.status === 'stale') && <span className="text-muted-sm">{proof.origin === 'human' ? 'Automatic updates allowed' : proof.status === 'supported' ? 'Updated automatically' : proof.status === 'stale' ? 'Needs assessment refresh' : 'More evidence needed'}{proof.coverage && ` · ${formatProfileCoverage(proof.coverage)}`}</span>}
              {count > 0 && <Link className="text-link" to={`/profiles/${edge.subject_id}?tab=evidence&target_id=${encodeURIComponent(edge.target_id)}`}>Meeting evidence ({count})</Link>}
            </div>
            <div className="flex-wrap relationship-actions">
              <button className="btn btn-sm" disabled={disabled || busy} onClick={() => { setNotice(null); setDraft({ edge, target: null, label: edge.label, notes: edge.notes, notesChanged: false, revision: profile.revision, refreshAfter: null }); }}>Edit relationship</button>
              {proof?.human && <button className="btn btn-sm" disabled={disabled || busy} onClick={() => release.mutate(edge)}>Allow automatic updates</button>}
              <button className="btn btn-sm btn-danger" disabled={disabled || busy} onClick={() => { if (confirm(`Remove the relationship from ${edge.subject_name} to ${edge.target_name}?`)) remove.mutate(edge); }}>Remove relationship</button>
            </div>
          </>}
        </section>;
      })}
    </article>)}
  </section>;
}
