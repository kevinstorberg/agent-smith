import { useCallback, useState } from 'react';
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
}

export function MeetingParticipants({ meetingId, onChanged }: { meetingId: string; onChanged: () => void }) {
  const read = useCallback(() => api.meetings.participants(meetingId), [meetingId]);
  const { data, loading, error, refresh } = useApiRead(read);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const change = useApiMutation({
    mutationFn: ({ revision, participants }: { revision: number; participants: MeetingParticipantInput[] }) =>
      api.meetings.updateParticipants(meetingId, { expected_revision: revision, participants }),
    onSuccess: () => {
      setDraft(null);
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
  usePolling(() => refresh({ showLoading: false }), { enabled: (!draft || Boolean(data?.running)) && !change.loading });

  const save = () => {
    if (!draft || !data || change.loading || data.running) return;
    if (!draft.name.trim()) { setNotice('A participant name is required.'); return; }
    const person: MeetingParticipantInput = {
      name: draft.name.trim(), ...(draft.email.trim() ? { email: draft.email.trim() } : {}),
      ...(draft.profileId ? { profile_id: draft.profileId } : {}), ...(draft.speakerKey ? { speaker_key: draft.speakerKey } : {}),
    };
    const retained = draft.originalSpeakerKey ? data.items.filter(person => person.speaker_key !== draft.originalSpeakerKey) : data.items;
    change.mutate({ revision: draft.conflicted ? data.revision : draft.revision, participants: [...retained, person] });
  };
  const selectProfile = (profile: ProfileSummary | null) => {
    if (draft) setDraft({ ...draft, profileId: profile?.id || '', ...(profile ? { name: profile.display_name, email: profile.email || '' } : {}) });
  };
  const open = (speakerKey = '') => {
    if (!data) return;
    const assignment = data.items.find(person => person.speaker_key === speakerKey);
    setNotice(null);
    setDraft({ name: assignment?.name || '', email: assignment?.email || '', profileId: assignment?.profile_id || '',
      speakerKey, originalSpeakerKey: assignment ? speakerKey : null, revision: data.revision, conflicted: false });
  };

  return <section id="meeting-participants" className="card meeting-participants" aria-label="Meeting participants">
    <div className="participants-header">
      <h3 className="section-title">Participants</h3>
      {data && <button className="btn" onClick={() => open()} disabled={change.loading || Boolean(draft) || data.running}>Add participant</button>}
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
          <button className="btn btn-sm" disabled={Boolean(draft) || data.running || change.loading} onClick={() => open(group.key)}>
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
          </div>
          <div className="participant-actions">
            {person.profile_id && <Link className="text-link" to={`/profiles/${person.profile_id}`}>Profile</Link>}
            <button className="btn btn-sm" disabled={Boolean(draft) || change.loading || data.running}
              onClick={() => change.mutate({ revision: data.revision, participants: data.items.filter((_, position) => position !== index) })}>Remove participant</button>
          </div>
        </li>)}</ul>
      </div>}
      {(data.stale_speaker_keys?.length || 0) > 0 && <div className="participant-group" role="alert">
        <p>Saved speaker assignments no longer match the transcript. Clear outdated assignments, then choose a current speaker.</p>
        <button className="btn" disabled={Boolean(draft) || change.loading || data.running} onClick={() => change.mutate({
          revision: data.revision,
          participants: data.items.map(person => person.speaker_key && data.stale_speaker_keys?.includes(person.speaker_key) ? { ...person, speaker_key: null } : person),
        })}>Clear outdated assignments</button>
      </div>}
      {data.running && <p className="text-muted-sm">Participant changes are available after processing finishes.</p>}
      {draft && <form className="participant-form" onSubmit={event => { event.preventDefault(); save(); }}>
        <p className="text-muted-sm">Add a person by name and email, or choose an existing profile. Select a transcript speaker to explicitly identify their words.</p>
        <ProfilePicker label="Find an existing profile" selectionLabel="Existing participant profile" value={draft.profileId} onSelect={selectProfile} limit={10}
          disabled={change.loading} emptyLabel="Enter a person manually" selectedLabel={draft.name} />
        {draft.profileId && <p className="text-muted-sm">This assigns the person to this meeting. <Link className="text-link" to={`/profiles/${draft.profileId}`} target="_blank" rel="noopener noreferrer">Manage linked emails</Link> on their profile for future meetings.</p>}
        <div>
          <label className="form-label" htmlFor="participant-name">Name</label>
          <input id="participant-name" className="input" disabled={change.loading || data.running} maxLength={200} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} />
        </div>
        <div>
          <label className="form-label" htmlFor="participant-email">Email</label>
          <input id="participant-email" className="input" disabled={change.loading || data.running} type="email" maxLength={320} value={draft.email} onChange={event => setDraft({ ...draft, email: event.target.value })} />
        </div>
        <div>
          <label className="form-label" htmlFor="participant-speaker">Transcript speaker</label>
          <select id="participant-speaker" className="input" disabled={change.loading || data.running} value={draft.speakerKey} onChange={event => setDraft({ ...draft, speakerKey: event.target.value })}>
            <option value="">Unassigned</option>
            {data.speakers.filter(group => group.key === draft.originalSpeakerKey || !data.items.some(person => person.speaker_key === group.key)).map(group =>
              <option key={group.key} value={group.key}>{group.label} · {group.segment_count} segments</option>)}
          </select>
        </div>
        {data.speakers.length === 0 && <p className="text-muted-sm">Speaker choices appear after the transcript is captured. Named speakers can also match an unambiguous participant name.</p>}
        <p className="text-muted-sm">Saved memories and completed persona reviews are retained.</p>
        <div className="flex-wrap">
          <button className="btn" type="submit" disabled={change.loading || data.running}>{change.loading ? 'Saving...' : 'Save participant'}</button>
          <button className="btn" type="button" disabled={change.loading} onClick={() => setDraft(null)}>Cancel</button>
        </div>
      </form>}
    </>}
  </section>;
}
