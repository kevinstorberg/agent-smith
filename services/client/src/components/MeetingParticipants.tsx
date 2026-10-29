import { useCallback, useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { MeetingParticipantInput, ProfileSummary } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePolling } from '../hooks/usePolling';

interface Draft {
  name: string;
  email: string;
  profileId: string;
  speakerKey: string;
  revision: number;
  conflicted: boolean;
}

export function MeetingParticipants({ meetingId, onChanged }: { meetingId: string; onChanged: () => void }) {
  const read = useCallback(() => api.meetings.participants(meetingId), [meetingId]);
  const { data, loading, error, refresh } = useApiRead(read);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState<ProfileSummary[]>([]);
  const search = useApiMutation({
    mutationFn: () => api.profiles.list({ q: query.trim() || undefined, limit: 10 }),
    onSuccess: result => setMatches(result.items),
    onError: () => setNotice('Could not search profiles. Try again.'),
  });
  const change = useApiMutation({
    mutationFn: ({ revision, participants }: { revision: number; participants: MeetingParticipantInput[] }) =>
      api.meetings.updateParticipants(meetingId, { expected_revision: revision, participants }),
    onSuccess: () => {
      setDraft(null);
      setNotice('Participants saved. Enrolled meetings will update their profiles on the next meeting job.');
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
  const process = useApiMutation({
    mutationFn: () => api.meetings.process(meetingId),
    onSuccess: result => {
      setNotice(result.status === 'done' ? 'This meeting is already processed.' : result.status === 'running'
        ? 'This meeting is processing.' : 'Queued for the next meeting job. Use Run Now in Jobs to process the queue sooner.');
      refresh({ showLoading: false });
      onChanged();
    },
    onError: failure => setNotice(failure instanceof ApiError ? failure.message : 'Could not queue this meeting. Try again.'),
  });
  usePolling(() => refresh({ showLoading: false }), { enabled: (!draft || Boolean(data?.running)) && !change.loading && !process.loading });

  const save = () => {
    if (!draft || !data) return;
    if (!draft.name.trim()) { setNotice('A participant name is required.'); return; }
    const person: MeetingParticipantInput = {
      name: draft.name.trim(), ...(draft.email.trim() ? { email: draft.email.trim() } : {}),
      ...(draft.profileId ? { profile_id: draft.profileId } : {}), ...(draft.speakerKey ? { speaker_key: draft.speakerKey } : {}),
    };
    change.mutate({ revision: draft.conflicted ? data.revision : draft.revision, participants: [...data.items, person] });
  };
  const selectProfile = (profileId: string) => {
    const profile = matches.find(item => item.id === profileId);
    if (draft) setDraft({ ...draft, profileId, ...(profile ? { name: profile.display_name, email: profile.email || '' } : {}) });
  };

  return <section className="card" aria-label="Meeting participants">
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
      <h3 className="section-title">Participants</h3>
      <button className="btn btn-primary" onClick={() => process.mutate()} disabled={process.loading || change.loading || Boolean(draft) || data?.running}>
        {process.loading ? 'Queuing...' : data?.running ? 'Processing...' : 'Process meeting'}
      </button>
    </div>
    <p className="text-muted-sm">Process this meeting even if it was imported earlier. The existing <Link to="/jobs">meeting job</Link> captures its transcript and generates missing memories and profiles.</p>
    {loading && !data && <p>Loading participants...</p>}
    {error && <div role="alert"><p>Could not load participants.</p><button className="btn" onClick={() => refresh()}>Retry</button></div>}
    {notice && <p role="status">{notice}</p>}
    {data && <>
      {data.provider_participants.length > 0 && <div>
        <p className="text-muted-sm">From the meeting connection</p>
        <ul>{data.provider_participants.map((person, index) => <li key={index}>{person.name || person.email || 'Unnamed participant'}{person.name && person.email ? ` · ${person.email}` : ''}</li>)}</ul>
      </div>}
      <ul>{data.items.map((person, index) => <li key={`${index}-${person.name}`} style={{ marginBottom: 8 }}>
        {person.name}{person.email ? ` · ${person.email}` : ''}
        {person.profile_id && <> · <Link to={`/profiles/${person.profile_id}`}>Profile</Link></>}
        {person.speaker_key && <> · {data.speakers.find(group => group.key === person.speaker_key)?.label || 'Speaker assignment needs updating'}</>}
        <button className="btn btn-sm" style={{ marginLeft: 12 }} disabled={Boolean(draft) || change.loading || data.running}
          onClick={() => change.mutate({ revision: data.revision, participants: data.items.filter((_, position) => position !== index) })}>Remove participant</button>
      </li>)}</ul>
      {(data.stale_speaker_keys?.length || 0) > 0 && <div role="alert">
        <p>Saved speaker assignments no longer match the transcript. Clear outdated assignments, then choose a current speaker.</p>
        <button className="btn" disabled={Boolean(draft) || change.loading || data.running} onClick={() => change.mutate({
          revision: data.revision,
          participants: data.items.map(person => person.speaker_key && data.stale_speaker_keys?.includes(person.speaker_key) ? { ...person, speaker_key: null } : person),
        })}>Clear outdated assignments</button>
      </div>}
      {data.running && <p className="text-muted-sm">Participant changes are available after processing finishes.</p>}
      {!draft ? <button className="btn" disabled={data.running || change.loading} onClick={() => {
        setNotice(null); setMatches([]); setQuery('');
        setDraft({ name: '', email: '', profileId: '', speakerKey: '', revision: data.revision, conflicted: false });
      }}>Add participant</button> : <form onSubmit={event => { event.preventDefault(); save(); }}>
        <p className="text-muted-sm">Add a person by name and email, or choose an existing profile. Select a transcript speaker to explicitly identify their words.</p>
        <label className="form-label" htmlFor="participant-profile-search">Find an existing profile</label>
        <div className="search-bar">
          <input id="participant-profile-search" value={query} maxLength={1000} onChange={event => setQuery(event.target.value)} />
          <button className="btn" type="button" onClick={() => search.mutate()} disabled={search.loading}>{search.loading ? 'Searching...' : 'Find profiles'}</button>
        </div>
        {matches.length > 0 && <select className="input" aria-label="Existing participant profile" value={draft.profileId} onChange={event => selectProfile(event.target.value)}>
          <option value="">Enter a person manually</option>
          {matches.map(profile => <option key={profile.id} value={profile.id}>{profile.display_name}{profile.email ? ` · ${profile.email}` : ''}</option>)}
        </select>}
        {draft.profileId && <p className="text-muted-sm">This assigns the person to this meeting. <Link to={`/profiles/${draft.profileId}`} target="_blank" rel="noopener noreferrer">Manage linked emails</Link> on their profile for future meetings.</p>}
        <label className="form-label" htmlFor="participant-name">Name</label>
        <input id="participant-name" className="input" maxLength={200} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} />
        <label className="form-label" htmlFor="participant-email">Email</label>
        <input id="participant-email" className="input" type="email" maxLength={320} value={draft.email} onChange={event => setDraft({ ...draft, email: event.target.value })} />
        <label className="form-label" htmlFor="participant-speaker">Transcript speaker</label>
        <select id="participant-speaker" className="input" value={draft.speakerKey} onChange={event => setDraft({ ...draft, speakerKey: event.target.value })}>
          <option value="">Unassigned</option>
          {data.speakers.filter(group => !data.items.some(person => person.speaker_key === group.key)).map(group =>
            <option key={group.key} value={group.key}>{group.label} · {group.segment_count} segments</option>)}
        </select>
        {data.speakers.length === 0 && <p className="text-muted-sm">Speaker choices appear after the transcript is captured. Named speakers can also match an unambiguous participant name.</p>}
        <p className="text-muted-sm">Changing speaker assignments updates this meeting’s profile analysis. Saved memories and correction history are retained.</p>
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button className="btn btn-primary" type="submit" disabled={change.loading || data.running}>{change.loading ? 'Saving...' : 'Save participant'}</button>
          <button className="btn" type="button" disabled={change.loading} onClick={() => setDraft(null)}>Cancel</button>
        </div>
      </form>}
    </>}
  </section>;
}
