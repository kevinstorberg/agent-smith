import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { MeetingParticipantInput, ProfileSummary } from '../api';
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
}

export function MeetingParticipants({ meetingId, onChanged, statement, onStatementClosed, onBusyChange }: {
  meetingId: string; onChanged: () => void; statement?: { id: string; text: string } | null; onStatementClosed?: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const read = useCallback(() => api.meetings.participants(meetingId), [meetingId]);
  const { data, loading, error, refresh } = useApiRead(read);
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
        setDraft(previous => previous && { ...previous, conflicted: true });
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
  usePolling(() => refresh({ showLoading: false }), { enabled: (!draft || Boolean(data?.running)) && !change.loading });
  useEffect(() => {
    if (!statement || !data || draft || change.loading || identification.loading) return;
    const assignment = data.items.find(person => person.segment_id === statement.id);
    setDraft({ name: assignment?.name || '', email: assignment?.email || '', profileId: assignment?.profile_id || '',
      speakerKey: '', segmentId: statement.id, transcriptHash: data.transcript_hash || null,
      statementText: statement.text,
      originalSpeakerKey: null, revision: data.revision, conflicted: false });
  }, [statement, data, draft, change.loading, identification.loading]);

  const save = () => {
    if (!draft || !data || change.loading || locked) return;
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
      {data.provider_participants.length > 0 && <div className="participant-group">
        <p className="text-muted-sm">From the meeting connection</p>
        <ul className="participant-list">{data.provider_participants.map((person, index) => <li className="participant-row" key={index}>
          <div className="participant-info"><span className="participant-name">{person.name || person.email || 'Unnamed participant'}</span>
            {person.name && person.email && <span className="text-muted-sm">{person.email}</span>}
          </div>
        </li>)}</ul>
      </div>}
      {data.speakers.length > 0 && <div className="participant-group">
        <h4>Transcript speakers</h4>
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
      </div>}
      {data.items.length > 0 && <div className="participant-group">
        <p className="text-muted-sm">Added participants</p>
        <ul className="participant-list">{data.items.map((person, index) => <li className="participant-row" key={`${index}-${person.name}`}>
          <div className="participant-info">
            <span className="participant-name">{person.name}</span>
            {person.email && <span className="text-muted-sm">{person.email}</span>}
            {person.speaker_key && <span className="text-muted-sm">{data.speakers.find(group => group.key === person.speaker_key)?.label || 'Speaker assignment needs updating'}</span>}
            {person.segment_id && <span className="text-muted-sm">Statement {person.segment_id}</span>}
          </div>
          <div className="participant-actions">
            {person.profile_id && <Link className="text-link" to={`/profiles/${person.profile_id}`}>Profile</Link>}
            <button className="btn btn-sm" disabled={Boolean(draft) || change.loading || locked}
              onClick={() => change.mutate({ revision: data.revision, participants: data.items.filter((_, position) => position !== index), transcriptHash: data.transcript_hash })}>Remove participant</button>
          </div>
        </li>)}</ul>
      </div>}
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
          <button className="btn" type="submit" disabled={change.loading || locked || transcriptChanged}>{change.loading ? 'Saving...' : 'Save participant'}</button>
          <button className="btn" type="button" disabled={change.loading} onClick={() => { setDraft(null); onStatementClosed?.(); }}>Cancel</button>
        </div>
      </form>}
    </>}
  </section>;
}
