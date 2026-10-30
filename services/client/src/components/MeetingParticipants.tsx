import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { MeetingParticipantInput, MeetingParticipants as ParticipantsState, ProfileSummary } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePolling } from '../hooks/usePolling';
import { ProfilePicker } from './ProfilePicker';

interface Draft {
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
  meetingId: string; active?: boolean; onChanged: () => void; statement?: { id: string; text: string } | null; onStatementClosed?: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const read = useCallback(() => api.meetings.participants(meetingId), [meetingId]);
  const { data, loading, error, refresh } = useApiRead(read, { enabled: active });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const locked = data?.edit_lock_reason === undefined ? Boolean(data?.running) : Boolean(data.edit_lock_reason);
  const transcriptChanged = Boolean(draft?.segmentId && draft.transcriptHash !== (data?.transcript_hash || null));
  const change = useApiMutation({
    mutationFn: ({ revision, participants, transcriptHash }: { revision: number; participants: MeetingParticipantInput[]; transcriptHash?: string | null }) =>
      api.meetings.updateParticipants(meetingId, { expected_revision: revision, participants, ...(transcriptHash ? { expected_transcript_hash: transcriptHash } : {}) }),
    onSuccess: () => {
      setDraft(null);
      onStatementClosed?.();
      setNotice('Speaker assignments saved. Completed persona reviews are preserved.');
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
    onSuccess: () => { setNotice('Participant identification queued. Saved memories are retained; profiles will use repaired assignments.'); refresh({ showLoading: false }); onChanged(); },
    onError: failure => setNotice(failure instanceof ApiError ? failure.message : 'Could not queue participant identification.'),
  });
  const busy = Boolean(draft) || change.loading || identification.loading;
  useEffect(() => { onBusyChange?.(busy); }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange?.(false), [onBusyChange]);
  usePolling(() => refresh({ showLoading: false }), { enabled: active && (!draft || Boolean(data?.running)) && !change.loading });
  useEffect(() => {
    if (!statement || !data || draft || change.loading || identification.loading) return;
    const assignment = data.items.find(person => person.segment_id === statement.id);
    setDraft({ name: assignment?.name || '', email: assignment?.email || '', profileId: assignment?.profile_id || '',
      speakerKey: '', segmentId: statement.id, transcriptHash: data.transcript_hash || null,
      statementText: statement.text,
      originalSpeakerKey: null, revision: data.revision, conflicted: false });
  }, [statement, data, draft, change.loading, identification.loading]);

  const save = () => {
    if (!draft || !data || change.loading || locked || loading || error || (draft.refreshAfter && draft.refreshAfter === data)) return;
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
    const assignment = data.items.find(person => person.speaker_key === speakerKey);
    setNotice(null);
    setDraft({ name: assignment?.name || '', email: assignment?.email || '', profileId: assignment?.profile_id || '',
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
  useEffect(() => {
    if (active && draft?.segmentId) document.getElementById('participant-name')?.focus();
  }, [active, draft?.segmentId]);
  if (!active) return null;
  return <section id="meeting-participants" className="card meeting-participants" aria-label="Meeting participants">
    <div className="participants-header">
      <h3 className="section-title">Participants</h3>
      {data && <button className="btn" onClick={() => open()} disabled={change.loading || Boolean(draft) || locked}>Add participant</button>}
    </div>
    <p className="text-muted-sm">Connect transcript speakers to people. Assignments label this transcript and identify speakers for future persona analysis.</p>
    {loading && !data && <p>Loading participants...</p>}
    {error && <div role="alert"><p>Could not load participants.</p><button className="btn" onClick={() => refresh()}>Retry</button></div>}
    {notice && <p role="status">{notice}</p>}
    {data && <>
      {data.people?.map(person => <article className="participant-person" key={person.key}>
        <div className="participants-header"><h4>{person.profile_id ? <Link className="text-link" to={`/profiles/${person.profile_id}`}>{person.display_name}</Link> : person.display_name}</h4>
          {person.sources.includes('provider') && <span className="tag tag-sm">From connection</span>}
        </div>
        {person.emails.length > 0 && <p className="text-muted-sm">{person.emails.join(' · ')}</p>}
        {person.names?.some(name => name !== person.display_name) && <p className="text-muted-sm">Also listed as: {person.names.filter(name => name !== person.display_name).join(' · ')}</p>}
        {person.assignments.length > 0 && <details><summary>{person.assignments.length} {person.assignments.length === 1 ? 'assignment' : 'assignments'}</summary>
          <ul className="participant-list">{person.assignments.map(assignment => <li className="participant-row" key={assignment.segment_id ? `statement:${assignment.segment_id}` : assignment.speaker_key ? `channel:${assignment.speaker_key}` : `roster:${JSON.stringify([assignment.profile_id, assignment.email, assignment.name])}`}>
            <div className="participant-info">{assignment.segment_id ? <a className="text-link" href={`#transcript-${assignment.segment_id}`}>Statement {assignment.segment_id}</a> : assignment.speaker_key ? <span>Audio channel: {data.speakers.find(group => group.key === assignment.speaker_key)?.label || 'Assignment needs updating'}</span> : <span>Meeting participant</span>}</div>
            <button className="btn btn-sm" disabled={Boolean(draft) || change.loading || locked || loading || Boolean(error)} onClick={() => removeAssignment(assignment)}>Remove assignment</button>
          </li>)}</ul>
        </details>}
      </article>)}
      {unlinked.length > 0 && <div className="participant-group"><h4>Unlinked attendees</h4><p className="text-muted-sm">Choose an existing profile when assigning statements to connect these names reliably.</p>
        <ul className="participant-list">{unlinked.map(({ source, participant }, index) => <li className="participant-row" key={`${source}-${index}`}>
          <div className="participant-info"><span className="participant-name">{participant.name || participant.email || 'Unnamed attendee'}</span>{participant.email && <span className="text-muted-sm">{participant.email}</span>}
            {participant.segment_id && <a className="text-link" href={`#transcript-${participant.segment_id}`}>Statement {participant.segment_id}</a>}
            {participant.speaker_key && <span className="text-muted-sm">Audio channel assignment</span>}
          </div>{source === 'manual' ? <button className="btn btn-sm" disabled={Boolean(draft) || change.loading || locked || loading || Boolean(error)} onClick={() => { if (participant.name) removeAssignment({ ...participant, name: participant.name }); }}>Remove assignment</button> : <span className="tag tag-sm">From connection</span>}
        </li>)}</ul>
      </div>}
      {data.speakers.length > 0 && <details className="participant-group"><summary>Audio channels ({data.speakers.length})</summary>
        <p className="text-muted-sm">A shared channel can contain several people. Assign individual statements in the transcript; a channel assignment applies to every statement in that channel.</p>
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
      {locked && <p className="text-muted-sm">{data.edit_lock_reason === 'capturing_transcript'
        ? 'Participant changes are available after transcript capture finishes.'
        : data.edit_lock_reason === 'identifying_participants' ? 'Participant changes are available after speaker identification finishes.'
        : data.edit_lock_reason === 'analyzing_personas' ? 'Participant changes are available after the current persona review finishes.'
        : 'Participant changes are available after processing finishes.'}</p>}
      {data.attribution && <div className="participant-group">
        <p className="text-muted-sm">Statement identification: {data.attribution.status}. {data.attribution.progress.processed_units} of {data.attribution.progress.total_units ?? '?'} statements reviewed.
          {data.attribution.status === 'done' && data.attribution.progress.total_units != null && ` ${data.attribution.progress.total_units - data.attribution.progress.saved_count} statements remain without automatic identification.`}
          {data.attribution.status === 'failed' && ' Uncertain statements stay unknown; memory and persona processing can continue.'}
          {data.attribution.error_type && ` Error: ${data.attribution.error_type}.`}</p>
        <button className="btn" disabled={data.running || identification.loading || Boolean(draft)} onClick={() => identification.mutate()}>
          {identification.loading ? 'Queuing...' : 'Identify participants'}</button>
      </div>}
      {draft && <form className="participant-form" onSubmit={event => { event.preventDefault(); save(); }}>
        {draft.refreshAfter && (draft.refreshAfter === data || error) && <p role="alert">Refresh the current participants before saving this draft. <button className="btn btn-sm" type="button" onClick={() => refresh()}>Refresh participants</button></p>}
        {transcriptChanged && <p role="alert">The transcript changed. Cancel this draft and select a current statement.</p>}
        <p className="text-muted-sm">Add a person by name and email, or choose an existing profile. Channel assignments label every statement in that channel. Use Assign this statement in the transcript when people share a channel.</p>
        <ProfilePicker label="Find an existing profile" selectionLabel="Existing participant profile" value={draft.profileId} onSelect={selectProfile} limit={10}
          disabled={change.loading} emptyLabel="Enter a person manually" selectedLabel={draft.name} />
        {draft.profileId && <p className="text-muted-sm">This assigns the person to this meeting. <Link className="text-link" to={`/profiles/${draft.profileId}`} target="_blank" rel="noopener noreferrer">Manage linked emails</Link> on their profile for future meetings.</p>}
        <div>
          <label className="form-label" htmlFor="participant-name">Name</label>
          <input id="participant-name" className="input" disabled={change.loading || locked} maxLength={200} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} />
        </div>
        <div>
          <label className="form-label" htmlFor="participant-email">Email</label>
          <input id="participant-email" className="input" disabled={change.loading || locked} type="email" maxLength={320} value={draft.email} onChange={event => setDraft({ ...draft, email: event.target.value })} />
        </div>
        {draft.segmentId ? <p className="text-muted-sm">Assign only statement {draft.segmentId}: <q>{draft.statementText}</q></p> : <div>
          <label className="form-label" htmlFor="participant-speaker">Transcript speaker</label>
          <select id="participant-speaker" className="input" disabled={change.loading || locked} value={draft.speakerKey} onChange={event => setDraft({ ...draft, speakerKey: event.target.value })}>
            <option value="">Unassigned</option>
            {data.speakers.filter(group => group.key === draft.originalSpeakerKey || !data.items.some(person => person.speaker_key === group.key)).map(group =>
              <option key={group.key} value={group.key}>{group.label} · {group.segment_count} segments</option>)}
          </select>
        </div>}
        {data.speakers.length === 0 && <p className="text-muted-sm">Speaker choices appear after the transcript is captured. Named speakers can also match an unambiguous participant name.</p>}
        <p className="text-muted-sm">Saved memories and completed persona reviews are retained.</p>
        <div className="flex-wrap">
          <button className="btn" type="submit" disabled={change.loading || locked || transcriptChanged || loading || Boolean(error) || Boolean(draft.refreshAfter && draft.refreshAfter === data)}>{change.loading ? 'Saving...' : 'Save participant'}</button>
          <button className="btn" type="button" disabled={change.loading} onClick={() => { setDraft(null); onStatementClosed?.(); }}>Cancel</button>
        </div>
      </form>}
    </>}
  </section>;
}
