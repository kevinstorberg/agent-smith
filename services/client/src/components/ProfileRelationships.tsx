import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { ParticipantProfile, ProfileRelationshipCard, ProfileSummary } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { formatProfileCoverage } from '../utils/profileFields';
import { ProfilePicker } from './ProfilePicker';

interface Draft {
  kind: 'create' | 'edit' | 'assign'; card: ProfileRelationshipCard | null;
  name: string; profileId: string | null; targetRevision: number | null;
  identityChanged: boolean; label: string; labelChanged: boolean; notes: string; notesChanged: boolean;
  revision: number; assignmentVersion: string | null;
}

export function ProfileRelationships({ profile, disabled, onBusyChange, onReload }: {
  profile: ParticipantProfile; disabled: boolean; onBusyChange: (busy: boolean) => void; onReload: () => void;
}) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshAfter, setRefreshAfter] = useState<ParticipantProfile | null>(null);
  const [targets, setTargets] = useState<ProfileSummary[]>([]);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const latestProfile = useRef(profile);
  const mutating = useRef(false);
  const assignmentDialog = useRef<HTMLDialogElement>(null);
  const assignmentButton = useRef<HTMLButtonElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const focusAfterClose = useRef<'assign' | 'add' | null>(null);
  useEffect(() => { latestProfile.current = profile; }, [profile]);
  useEffect(() => {
    if (draft?.kind === 'assign' && assignmentDialog.current && !assignmentDialog.current.open) assignmentDialog.current.showModal();
    else if (draft?.kind !== 'assign' && focusAfterClose.current) {
      (focusAfterClose.current === 'assign' ? assignmentButton.current || addButton.current : addButton.current)?.focus();
      focusAfterClose.current = null;
    }
  }, [draft?.kind]);
  const cards = profile.relationship_cards;
  const currentCard = draft?.card ? cards.find(card => card.id === draft.card!.id) : undefined;
  const unassigned = profile.relationship_unassigned;
  const waitingForRefresh = refreshAfter !== null && profile === refreshAfter;
  const unavailable = Boolean(draft?.card && (!currentCard || (currentCard.status === 'stale' && !currentCard.notes && draft.card.status !== 'stale')))
    || Boolean(draft?.kind === 'assign' && !unassigned);
  const refreshedCard = refreshAfter !== null && !waitingForRefresh ? currentCard : undefined;
  const name = refreshedCard && !draft?.identityChanged ? refreshedCard.name : draft?.name || '';
  const profileId = refreshedCard && !draft?.identityChanged ? refreshedCard.profile_id : draft?.profileId;
  const label = refreshedCard && !draft?.labelChanged ? refreshedCard.label : draft?.label || '';
  const notes = draft?.kind === 'assign' ? unassigned?.notes || '' : refreshedCard && !draft?.notesChanged ? refreshedCard.notes : draft?.notes || '';
  const closeDraft = (restoreAssignmentFocus: boolean) => {
    if (draft?.kind === 'assign') focusAfterClose.current = restoreAssignmentFocus ? 'assign' : 'add';
    setDraft(null); setNotice(null); setRefreshAfter(null);
  };
  const cancel = () => closeDraft(true);
  const failed = (error: Error) => {
    if (error instanceof ApiError && error.status === 409) {
      setRefreshAfter(latestProfile.current);
      setRefreshVersion(value => value + 1);
      setNotice('This relationship changed. Review the refreshed analysis before saving again.');
      onReload();
    } else if (error instanceof ApiError && error.status === 422) setNotice(error.message);
    else setNotice(draft ? 'Could not save this relationship. Your draft is retained.' : 'Could not update this relationship. Refresh and try again.');
  };
  const saved = () => { closeDraft(false); onReload(); };
  const save = useApiMutation({ mutationFn: () => {
    const edit = draft!;
    const identity = edit.identityChanged || !edit.card ? {
      name: edit.name.trim(), profile_id: edit.profileId,
      ...(edit.profileId ? { target_revision: refreshAfter === null ? edit.targetRevision! : targets.find(target => target.id === edit.profileId)?.revision ?? edit.targetRevision! } : {}),
    } : {};
    const notes = edit.notesChanged ? { notes: edit.notes.trim() } : {};
    if (edit.card) return api.profiles.updateRelationshipCard(profile.id, edit.card.id, {
      version: refreshAfter === null ? edit.card.version : currentCard!.version,
      ...identity, label: label.trim(), ...notes,
    });
    return api.profiles.createRelationshipCard(profile.id, {
      expected_revision: refreshAfter === null ? edit.revision : profile.revision,
      name: edit.name.trim(), ...identity, label: edit.label.trim(), ...notes,
      ...(edit.kind === 'assign' ? { assignment_version: refreshAfter === null ? edit.assignmentVersion! : unassigned!.version } : {}),
    });
  }, onSuccess: saved, onError: failed });
  const remove = useApiMutation({ mutationFn: (card: ProfileRelationshipCard) => api.profiles.removeRelationshipCard(profile.id, card.id, card.version), onSuccess: saved, onError: failed });
  const release = useApiMutation({ mutationFn: (card: ProfileRelationshipCard) => api.profiles.updateRelationshipCard(profile.id, card.id, { version: card.version, allow_agent_notes: true }), onSuccess: saved, onError: failed });
  const saving = save.loading || remove.loading || release.loading;
  const busy = Boolean(draft) || saving;
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);
  const mutate = (operation: () => Promise<void>) => {
    if (mutating.current) return;
    mutating.current = true;
    void operation().finally(() => { mutating.current = false; });
  };
  const canSave = !saving && !waitingForRefresh && !unavailable;
  const start = (card: ProfileRelationshipCard | null, assign = false) => {
    setNotice(null); setRefreshAfter(null);
    setDraft({ kind: card ? 'edit' : assign ? 'assign' : 'create', card,
      name: card?.name || '', profileId: card?.profile_id || null, targetRevision: null,
      identityChanged: false, label: card?.label || '', labelChanged: false, notes: card?.notes || '', notesChanged: false,
      revision: profile.revision, assignmentVersion: assign ? unassigned!.version : null });
  };
  const editor = draft && <form className="participant-form" aria-label={draft.kind === 'assign' ? 'Assign saved analysis' : draft.card ? `Edit relationship with ${draft.card.name}` : 'New relationship'} onSubmit={event => {
    event.preventDefault(); if (!canSave || mutating.current) return;
    if (!draft.name.trim()) { setNotice('Enter the person’s name or select a profile.'); return; }
    mutate(() => save.mutate());
  }}>
    {unavailable ? <p>This relationship or its saved analysis is no longer available. Refresh or cancel to return to the current relationships.</p> : <>
      <div><label className="form-label" htmlFor="relationship-name">Name</label>
        <input id="relationship-name" className="input" disabled={saving} readOnly={Boolean(profileId)} required maxLength={200} value={name}
          onChange={event => setDraft({ ...draft, name: event.target.value, identityChanged: true })} /></div>
      <ProfilePicker label="Find a profile (optional)" selectionLabel="Linked profile" value={profileId || ''} selectedLabel={name}
        emptyLabel="No linked profile" preserveSelectionOnSearch excludeId={profile.id} disabled={saving} refreshVersion={refreshVersion} onResults={setTargets}
        onSelect={target => setDraft({ ...draft, profileId: target?.id || null, targetRevision: target?.revision ?? null, name: target?.display_name || name, identityChanged: true })} />
      <div><label className="form-label" htmlFor="relationship-notes">Analysis</label>
        <textarea id="relationship-notes" className="input" disabled={saving} readOnly={draft.kind === 'assign'} rows={6} maxLength={4000}
          value={notes} onChange={event => setDraft({ ...draft, notes: event.target.value, notesChanged: true })} /></div>
      <div><label className="form-label" htmlFor="relationship-label">Relationship label (optional)</label>
        <input id="relationship-label" className="input" disabled={saving} maxLength={200} value={label} placeholder="e.g. colleague" onChange={event => setDraft({ ...draft, label: event.target.value, labelChanged: true })} /></div>
      <p className="text-muted-sm">{draft.kind === 'assign' ? 'Choose the person described by this analysis. Enter a name or link an existing profile.' : 'Your analysis edits, including an empty analysis, stay protected from automatic updates.'}</p>
      {refreshAfter !== null && <div role="region" aria-label="Current saved analysis">
        <p><strong>Current saved analysis</strong></p>
        {!waitingForRefresh && currentCard && <p className="text-muted-sm">{currentCard.name}{currentCard.label && ` · ${currentCard.label}`}</p>}
        <p style={{ whiteSpace: 'pre-wrap' }}>{waitingForRefresh ? 'Waiting for refreshed information. Your draft is retained.' : (currentCard?.notes ?? unassigned?.notes) || 'The saved analysis is empty.'}</p>
      </div>}
    </>}
    {(waitingForRefresh || unavailable) && <button className="btn btn-sm" type="button" disabled={saving} onClick={onReload}>Retry relationship refresh</button>}
    <div className="flex-wrap"><button className="btn" disabled={!canSave}>{save.loading ? 'Saving...' : draft.kind === 'assign' ? 'Assign analysis' : 'Save relationship'}</button>
      <button className="btn" type="button" disabled={saving} onClick={cancel}>Cancel</button></div>
  </form>;
  return <section aria-label="Profile relationships">
    <div className="page-header profiles-header"><h3 className="section-title">Relationships</h3>
      <div className="flex-wrap">
        {unassigned && <button ref={assignmentButton} className="btn" disabled={disabled || busy || waitingForRefresh} onClick={() => start(null, true)}>Assign saved analysis</button>}
        <button ref={addButton} className="btn" disabled={disabled || busy || waitingForRefresh} onClick={() => start(null)}>Add relationship</button>
      </div>
    </div>
    {notice && draft?.kind !== 'assign' && <p className="card" role="alert">{notice}{!draft && waitingForRefresh && <button className="btn btn-sm" onClick={onReload}>Retry relationship refresh</button>}</p>}
    {draft?.kind === 'create' && <section className="card" aria-label="New relationship">{editor}</section>}
    {draft?.kind === 'assign' && <dialog ref={assignmentDialog} className="relationship-assignment-dialog" aria-label="Assign saved analysis" onCancel={event => { event.preventDefault(); if (!saving) cancel(); }}>
      <h3>Assign saved analysis</h3>{notice && <p role="alert">{notice}</p>}{editor}
    </dialog>}
    {draft?.kind === 'edit' && !currentCard && <section className="card" aria-label="Relationship draft recovery">{editor}</section>}
    {cards.length === 0 && <p className="card text-muted-sm">No relationships saved yet. Add a person to begin.</p>}
    {cards.map(card => <article key={card.id} className="card relationship-person" aria-label={`Relationship with ${card.name}`}>
      <h4 className="relationship-person-name">{card.profile_id ? <Link className="text-link" to={`/profiles/${card.profile_id}`}>{card.name}</Link> : card.name}</h4>
      <div className="markdown-content" role="region" aria-label={`Relationship analysis for ${card.name}`}>
        {draft?.card?.id === card.id ? editor : card.notes ? <ReactMarkdown>{card.notes}</ReactMarkdown> : <p className="text-muted-sm">{card.human ? 'You have kept this analysis empty.' : card.status === 'stale' ? 'This analysis needs a refresh.' : card.status === 'insufficient_evidence' ? 'More evidence is needed to build this analysis.' : 'This analysis has not been generated yet.'}</p>}
      </div>
      {draft?.card?.id !== card.id && <>
        <div className="flex-wrap relationship-evidence">
          {card.label && <span className="tag">{card.label}</span>}
          {card.human ? <span className="tag">Edited by you</span> : card.notes && <span className="text-muted-sm">{card.status === 'supported' ? 'Updated automatically' : card.status === 'stale' ? 'Needs assessment refresh' : 'Saved analysis'}</span>}
          {card.coverage.claim_count > 0 && <span className="text-muted-sm">{formatProfileCoverage(card.coverage)}</span>}
          {card.evidence_links.map(link => <Link key={`${link.profile_id}-${link.target_id}`} className="text-link" to={`/profiles/${link.profile_id}?tab=evidence&target_id=${encodeURIComponent(link.target_id)}`}>Meeting evidence ({link.count})</Link>)}
        </div>
        <div className="flex-wrap relationship-actions">
          <button className="btn btn-sm" disabled={disabled || busy || waitingForRefresh} onClick={() => start(card)}>Edit relationship</button>
          {card.human && <button className="btn btn-sm" disabled={disabled || busy || waitingForRefresh} onClick={() => mutate(() => release.mutate(card))}>Allow automatic updates</button>}
          <button className="btn btn-sm btn-danger" disabled={disabled || busy || waitingForRefresh} onClick={() => { if (confirm(`Remove the relationship with ${card.name}?`)) mutate(() => remove.mutate(card)); }}>Remove relationship</button>
        </div>
      </>}
    </article>)}
  </section>;
}
