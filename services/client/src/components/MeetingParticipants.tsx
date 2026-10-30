import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { MeetingParticipantInput, MeetingParticipants as ParticipantsState, ProfileSummary } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePolling } from '../hooks/usePolling';
import { ProfilePicker } from './ProfilePicker';

interface Draft {
  mode: 'profile' | 'manual';
  name: string;
  email: string;
  profileId: string;
  speakerKey: string;
  revision: number;
  conflicted: boolean;
  originalSpeakerKey: string | null;
  segmentId: string;
  statementText: string;
  transcriptHash: string | null;
  refreshAfter?: ParticipantsState | null;
}

export function MeetingParticipants({ meetingId, onChanged, statement, onStatementClosed, onBusyChange, active = true }: {
  meetingId: string; active?: boolean; onChanged: () => void; statement?: { id: string; text: string; transcriptHash: string | null } | null; onStatementClosed?: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const read = useCallback(() => api.meetings.participants(meetingId), [meetingId]);
  const { data, loading, error, refresh } = useApiRead(read, { enabled: active });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [queuedAfter, setQueuedAfter] = useState<ParticipantsState | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const restoreFocus = useRef(false);
  const identifying = useRef(false);
  const editorOpen = Boolean(draft);
  const mode = draft?.mode;
  const closeEditor = () => { restoreFocus.current = true; setDraft(null); onStatementClosed?.(); };
  useEffect(() => {
    if (!active) { restoreFocus.current = false; return; }
    if (editorOpen && dialog.current) {
      if (!dialog.current.open) dialog.current.showModal();
      dialog.current.querySelector<HTMLInputElement>('input')?.focus();
    } else if (restoreFocus.current) {
      if (trigger.current?.isConnected) trigger.current.focus();
      restoreFocus.current = false;
    }
  }, [active, editorOpen, mode]);
  const locked = data?.edit_lock_reason === undefined ? Boolean(data?.running) : Boolean(data.edit_lock_reason);
  const transcriptChanged = Boolean(draft?.segmentId && (!draft.transcriptHash || draft.transcriptHash !== (data?.transcript_hash || null)));
  const change = useApiMutation({
    mutationFn: ({ revision, participants, transcriptHash }: { revision: number; participants: MeetingParticipantInput[]; transcriptHash?: string | null }) =>
      api.meetings.updateParticipants(meetingId, { expected_revision: revision, participants, ...(transcriptHash ? { expected_transcript_hash: transcriptHash } : {}) }),
    onSuccess: () => {
      closeEditor();
      setNotice('Participant saved.');
      refresh({ showLoading: false });
      onChanged();
    },
    onError: failure => {
      if (failure instanceof ApiError && failure.status === 409) {
        setDraft(previous => previous && { ...previous, conflicted: true, refreshAfter: data });
        setNotice(`${failure.message} Review the latest participants before saving again.`);
        refresh({ showLoading: false });
      } else {
        setNotice(failure instanceof ApiError ? failure.message : 'Could not save participants. Try again.');
      }
    },
  });
  const identification = useApiMutation({
    mutationFn: () => api.meetings.identifyParticipants(meetingId),
    onSuccess: () => { setQueuedAfter(data); setNotice('Speaker identification queued for the next meeting job run.'); refresh({ showLoading: false }); onChanged(); },
    onError: failure => setNotice(failure instanceof ApiError ? failure.message : 'Could not queue participant identification.'),
  });
  const busy = Boolean(draft) || change.loading || identification.loading;
  useEffect(() => {
    if (queuedAfter && data !== queuedAfter && data?.attribution && ['pending', 'running', 'done', 'failed'].includes(data.attribution.status)) setQueuedAfter(null);
  }, [data, queuedAfter]);
  useEffect(() => { onBusyChange?.(busy); }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange?.(false), [onBusyChange]);
  usePolling(() => refresh({ showLoading: false }), { enabled: active && (!draft || Boolean(data?.running)) && !change.loading });
  useEffect(() => {
    if (!statement || !data || draft || change.loading || identification.loading) return;
    trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const assignment = data.items.find(person => person.segment_id === statement.id);
    setDraft({ mode: assignment && !assignment.profile_id ? 'manual' : 'profile', name: assignment?.name || '', email: assignment?.email || '', profileId: assignment?.profile_id || '',
      speakerKey: '', segmentId: statement.id, transcriptHash: statement.transcriptHash,
      statementText: statement.text,
      originalSpeakerKey: null, revision: data.revision, conflicted: false });
  }, [statement, data, draft, change.loading, identification.loading]);

  const save = () => {
    if (!draft || !data || change.loading || locked || loading || error || (draft.refreshAfter && draft.refreshAfter === data)) return;
    if (draft.mode === 'profile' && !draft.profileId) return;
    if (transcriptChanged) { setNotice('The transcript changed. Cancel this draft and select a current statement.'); return; }
    if (!draft.name.trim()) { setNotice('A participant name is required.'); return; }
    const person: MeetingParticipantInput = {
      name: draft.name.trim(), ...(draft.email.trim() ? { email: draft.email.trim() } : {}),
      ...(draft.profileId ? { profile_id: draft.profileId } : {}), ...(draft.speakerKey ? { speaker_key: draft.speakerKey } : {}),
      ...(draft.segmentId ? { segment_id: draft.segmentId } : {}),
    };
    const retained = draft.segmentId ? data.items.filter(person => person.segment_id !== draft.segmentId)
      : draft.originalSpeakerKey ? data.items.filter(person => person.speaker_key !== draft.originalSpeakerKey) : data.items;
    change.mutate({ revision: draft.conflicted ? data.revision : draft.revision, participants: [...retained, person],
      transcriptHash: draft.conflicted ? data.transcript_hash : draft.transcriptHash });
  };
  const selectProfile = (profile: ProfileSummary | null) => {
    if (draft) setDraft({ ...draft, profileId: profile?.id || '', ...(profile ? { name: profile.display_name, email: profile.email || '' } : {}) });
  };
  const open = (speakerKey = '') => {
    if (!data) return;
    trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const assignment = data.items.find(person => person.speaker_key === speakerKey);
    setNotice(null);
    setDraft({ mode: assignment && !assignment.profile_id ? 'manual' : 'profile', name: assignment?.name || '', email: assignment?.email || '', profileId: assignment?.profile_id || '',
      speakerKey, originalSpeakerKey: assignment ? speakerKey : null, segmentId: '', statementText: '', transcriptHash: data.transcript_hash || null,
      revision: data.revision, conflicted: false });
  };

  const removeAssignment = (assignment: MeetingParticipantInput) => {
    if (!data || change.loading || draft || locked || loading || error) return;
    const fields = ['name', 'email', 'profile_id', 'speaker_key', 'segment_id'] as const;
    const index = data.items.findIndex(item => fields.every(field => (item[field] ?? null) === (assignment[field] ?? null)));
    if (index < 0) { setNotice('This assignment changed. Refresh participants before removing it.'); return; }
    change.mutate({ revision: data.revision, participants: data.items.filter((_, position) => position !== index), transcriptHash: data.transcript_hash });
  };
  const unlinked: { source: 'provider' | 'manual'; participant: Partial<MeetingParticipantInput> }[] = data?.unlinked_attendees ?? (data?.people === undefined ? [
    ...(data?.provider_participants || []).map(participant => ({ source: 'provider' as const, participant })),
    ...(data?.items || []).map(participant => ({ source: 'manual' as const, participant })),
  ] : []);
  const attribution = data?.attribution;
  const identificationPending = Boolean(queuedAfter) || attribution?.status === 'pending' || attribution?.status === 'running';
  const identify = () => {
    if (!data || data.running || draft || identificationPending || identification.loading || identifying.current || loading || error || attribution?.status === 'not_imported') return;
    if (!window.confirm('Identify speakers on the next meeting job run? This uses your configured model and may incur charges. Saved memories are kept. Profile analysis will use repaired speaker assignments.')) return;
    identifying.current = true;
    identification.mutate().finally(() => { identifying.current = false; });
  };
  const reviewSummary = queuedAfter || attribution?.status === 'pending' ? 'Queued for the next meeting job run.'
    : attribution?.status === 'running' ? attribution.progress.total_units == null ? 'Reviewing transcript statements…' : `Reviewing ${attribution.progress.processed_units} of ${attribution.progress.total_units} statements.`
    : attribution?.status === 'done' ? `${attribution.progress.saved_count} statements automatically identified${attribution.progress.total_units == null ? '.' : ` · ${Math.max(0, attribution.progress.total_units - attribution.progress.saved_count)} unassigned.`}`
    : attribution?.status === 'failed' ? 'Speaker identification needs attention. You can assign statements manually or try again.'
    : attribution?.status === 'not_imported' ? 'Capture the transcript to identify speakers.' : 'Not reviewed.';
  const editorTitle = draft?.segmentId ? 'Assign statement' : draft?.speakerKey ? 'Assign audio channel' : 'Add participant';
  const lockMessage = data?.edit_lock_reason === 'capturing_transcript'
    ? 'Participant changes are available after transcript capture finishes.'
    : data?.edit_lock_reason === 'identifying_participants' ? 'Participant changes are available after speaker identification finishes.'
    : data?.edit_lock_reason === 'analyzing_personas' ? 'Participant changes are available after the current persona review finishes.'
    : 'Participant changes are available after processing finishes.';
  if (!active) return null;
  return <section id="meeting-participants" className="card meeting-participants" aria-label="Meeting participants">
    <div className="participants-header">
      <h3 className="section-title">Participants</h3>
      {data && <div className="participant-actions">
        {attribution && <button className="btn" onClick={identify} disabled={data.running || identification.loading || identificationPending || Boolean(draft) || loading || Boolean(error) || attribution.status === 'not_imported'}>{identification.loading ? 'Queuing...' : 'Identify speakers'}</button>}
        <button className="btn" onClick={() => open()} disabled={change.loading || Boolean(draft) || locked || loading || Boolean(error)}>Add participant</button>
      </div>}
    </div>
    {loading && !data && <p>Loading participants...</p>}
    {error && <div role="alert"><p>Could not load participants.</p><button className="btn" onClick={() => refresh()}>Retry</button></div>}
    {notice && !draft && <p role="status">{notice}</p>}
    {data && <>
      {attribution && <div className="participant-review">
        <p className="text-muted-sm">{reviewSummary}</p>
        {attribution.error_type && <details><summary>Technical details</summary><p className="text-muted-sm">{attribution.error_type}</p></details>}
      </div>}
      {(Boolean(data.people?.length) || unlinked.length > 0) ? <ul className="participant-list" aria-label="Meeting participants">
        {data.people?.map(person => <li className="participant-row participant-person" key={person.key}>
          <div className="participant-info"><span className="participant-name">{person.display_name}</span>
            {person.emails.length > 0 && <span className="text-muted-sm">{person.emails.join(' · ')}</span>}
          </div>
          {person.sources.includes('provider') && <span className="tag tag-sm">From connection</span>}
          {person.profile_id && <Link className="btn btn-sm" to={`/profiles/${person.profile_id}`}>View profile</Link>}
          {person.assignments.length > 0 && <details className="participant-assignments"><summary>{person.assignments.length} {person.assignments.length === 1 ? 'assignment' : 'assignments'}</summary>
          <ul className="participant-list">{person.assignments.map(assignment => <li className="participant-row" key={assignment.segment_id ? `statement:${assignment.segment_id}` : assignment.speaker_key ? `channel:${assignment.speaker_key}` : `roster:${JSON.stringify([assignment.profile_id, assignment.email, assignment.name])}`}>
            <div className="participant-info">{assignment.segment_id ? <a className="text-link" href={`#transcript-${assignment.segment_id}`}>Statement {assignment.segment_id}</a> : assignment.speaker_key ? <span>Audio channel: {data.speakers.find(group => group.key === assignment.speaker_key)?.label || 'Assignment needs updating'}</span> : <span>Meeting participant</span>}</div>
            <button className="btn btn-sm" disabled={Boolean(draft) || change.loading || locked || loading || Boolean(error)} onClick={() => removeAssignment(assignment)}>Remove assignment</button>
          </li>)}</ul>
        </details>}
        </li>)}
        {unlinked.map(({ source, participant }, index) => <li className="participant-row" key={`${source}-${index}`}>
          <div className="participant-info"><span className="participant-name">{participant.name || participant.email || 'Unnamed attendee'}</span>{participant.email && <span className="text-muted-sm">{participant.email}</span>}
            {participant.segment_id && <a className="text-link" href={`#transcript-${participant.segment_id}`}>Statement {participant.segment_id}</a>}
            {participant.speaker_key && <span className="text-muted-sm">Audio channel assignment</span>}
          </div>{source === 'manual' ? <button className="btn btn-sm" disabled={Boolean(draft) || change.loading || locked || loading || Boolean(error)} onClick={() => { if (participant.name) removeAssignment({ ...participant, name: participant.name }); }}>Remove assignment</button> : <span className="tag tag-sm">From connection</span>}
        </li>)}
      </ul> : <p className="text-muted-sm">No participants added. Choose a profile or add a name to get started.</p>}
      {data.speakers.length > 0 && <details className="participant-group"><summary>Audio channels ({data.speakers.length})</summary>
        <p className="text-muted-sm">A shared channel can contain several people. A channel assignment labels every statement in that channel.</p>
        <ul className="participant-list">{data.speakers.map(group => <li className="participant-row" key={group.key}>
          <div className="participant-info">
            <span className="participant-name">{group.effective_speaker?.display_name || group.label}</span>
            <span className="text-muted-sm">{[group.label, group.source, group.attribution].filter(Boolean).join(' · ')} · {group.segment_count} segments</span>
            {group.sample && <q className="text-muted-sm">{group.sample}</q>}
          </div>
          <button className="btn btn-sm" disabled={Boolean(draft) || locked || change.loading} onClick={() => open(group.key)}>
            {data.items.some(person => person.speaker_key === group.key) ? 'Edit assignment' : 'Assign speaker'}
          </button>
        </li>)}</ul>
      </details>}
      {(data.stale_speaker_keys?.length || 0) > 0 && <div className="participant-group" role="alert">
        <p>Saved speaker assignments no longer match the transcript. Clear outdated assignments, then choose a current speaker.</p>
        <button className="btn" disabled={Boolean(draft) || change.loading || locked} onClick={() => change.mutate({
          revision: data.revision,
          transcriptHash: data.transcript_hash,
          participants: data.items.map(person => person.speaker_key && data.stale_speaker_keys?.includes(person.speaker_key) ? { ...person, speaker_key: null } : person),
        })}>Clear outdated assignments</button>
      </div>}
      {(data.stale_segment_ids?.length || 0) > 0 && <div className="participant-group" role="alert">
        <p>Saved statement assignments no longer match the transcript. Clear outdated assignments, then assign a current statement.</p>
        <button className="btn" disabled={Boolean(draft) || change.loading || locked} onClick={() => change.mutate({
          revision: data.revision, transcriptHash: data.transcript_hash,
          participants: data.items.map(person => person.segment_id && data.stale_segment_ids?.includes(person.segment_id) ? { ...person, segment_id: null } : person),
        })}>Clear outdated statement assignments</button>
      </div>}
      {locked && !draft && <p className="text-muted-sm">{lockMessage}</p>}
      {draft && <dialog ref={dialog} className="meeting-participant-dialog" aria-label={editorTitle} onCancel={event => { event.preventDefault(); if (!change.loading) closeEditor(); }}>
        <h3>{editorTitle}</h3>
        {draft.segmentId && <blockquote className="participant-statement">{draft.statementText}</blockquote>}
        {draft.speakerKey && <p className="text-muted-sm">Assign every statement in {data.speakers.find(group => group.key === draft.speakerKey)?.label || 'this audio channel'} to one person.</p>}
        <form className="participant-form" onSubmit={event => { event.preventDefault(); save(); }}>
        {notice && <p role="status">{notice}</p>}
        {locked && <p className="text-muted-sm">{lockMessage}</p>}
        {draft.refreshAfter && (draft.refreshAfter === data || error) && <p role="alert">Refresh the current participants before saving this draft. <button className="btn btn-sm" type="button" onClick={() => refresh()}>Refresh participants</button></p>}
        {transcriptChanged && <p role="alert">The transcript changed. Cancel this draft and select a current statement. <button className="btn btn-sm" type="button" disabled={change.loading} onClick={() => { closeEditor(); refresh({ showLoading: false }); onChanged(); }}>Reload transcript</button></p>}
        <div className="sub-tabs participant-mode" role="group" aria-label="Participant source">
          {([['profile', 'Existing profile'], ['manual', 'Name and email']] as const).map(([value, label]) => <button key={value} className={`btn${draft.mode === value ? ' active' : ''}`} type="button" aria-pressed={draft.mode === value} disabled={change.loading || locked} onClick={() => { if (draft.mode !== value) setDraft({ ...draft, mode: value, profileId: '' }); }}>{label}</button>)}
        </div>
        {draft.mode === 'profile' ? <>
          <ProfilePicker label="Find an existing profile" selectionLabel="Existing participant profile" value={draft.profileId} onSelect={selectProfile} limit={10}
            disabled={change.loading || locked} emptyLabel="Select a profile" selectedLabel={draft.name} />
          {draft.profileId && <div className="participant-selection"><strong>{draft.name}</strong>{draft.email && <span className="text-muted-sm">{draft.email}</span>}<Link className="text-link" to={`/profiles/${draft.profileId}`} target="_blank" rel="noopener noreferrer">View profile</Link></div>}
        </> : <><div>
          <label className="form-label" htmlFor="participant-name">Name</label>
          <input id="participant-name" className="input" disabled={change.loading || locked} maxLength={200} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} />
        </div>
        <div>
          <label className="form-label" htmlFor="participant-email">Email (optional)</label>
          <input id="participant-email" className="input" disabled={change.loading || locked} type="email" maxLength={320} value={draft.email} onChange={event => setDraft({ ...draft, email: event.target.value })} />
        </div></>}
        <div className="flex-wrap">
          <button className="btn btn-primary" type="submit" disabled={change.loading || locked || transcriptChanged || loading || Boolean(error) || !draft.name.trim() || (draft.mode === 'profile' && !draft.profileId) || Boolean(draft.refreshAfter && draft.refreshAfter === data)}>{change.loading ? 'Saving...' : editorTitle}</button>
          <button className="btn" type="button" disabled={change.loading} onClick={closeEditor}>Cancel</button>
        </div>
      </form></dialog>}
    </>}
  </section>;
}
