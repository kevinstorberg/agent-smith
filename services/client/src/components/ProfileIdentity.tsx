import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { ParticipantProfile, ProfileSummary } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { PROFILE_SCOPE_LABELS } from '../utils/profiles';

interface Props {
  profile: ParticipantProfile;
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
  onReload: () => void;
  onSaved: (profile: ParticipantProfile) => void;
}

export function ProfileIdentity({ profile, disabled, onBusyChange, onReload, onSaved }: Props) {
  const [mode, setMode] = useState<'merge' | 'email' | null>(null);
  const [revision, setRevision] = useState(profile.revision);
  const [queryText, setQueryText] = useState('');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<ProfileSummary | null>(null);
  const [email, setEmail] = useState('');
  const [conflicted, setConflicted] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const read = useCallback(() => mode === 'merge' ? api.profiles.list({ q: query || undefined, limit: 25 }) : Promise.resolve({ items: [], total: 0 }), [mode, query]);
  const targets = useApiRead(read);
  const failed = (failure: Error) => {
    if (failure instanceof ApiError && failure.status === 409) {
      setConflicted(true);
      setNotice(mode === 'email' ? failure.message : 'A profile changed. Review the refreshed profiles and try again.');
      onReload(); targets.refresh();
    } else setNotice('Could not update the linked identities. Check your selection or email and try again.');
  };
  const succeeded = (winner: ParticipantProfile) => { setMode(null); setNotice(null); onSaved(winner); };
  const merge = useApiMutation({
    mutationFn: (target: ProfileSummary) => api.profiles.merge(profile.id, {
      target_id: target.id, expected_revision: conflicted ? profile.revision : revision,
      target_revision: conflicted ? targets.data?.items.find(item => item.id === target.id)?.revision ?? target.revision : target.revision,
    }),
    onSuccess: succeeded, onError: failed,
  });
  const link = useApiMutation({
    mutationFn: () => api.profiles.linkEmail(profile.id, { email: email.trim(), expected_revision: conflicted ? profile.revision : revision }),
    onSuccess: succeeded, onError: failed,
  });
  const saving = merge.loading || link.loading;
  useEffect(() => { onBusyChange(Boolean(mode) || saving); }, [mode, saving, onBusyChange]);
  const open = (value: 'merge' | 'email') => {
    setMode(value); setRevision(profile.revision); setConflicted(false); setNotice(null); setSelected(null);
  };
  const submitMerge = () => {
    if (!selected) { setNotice('Select the profile that should receive this profile.'); return; }
    if (confirm(`Merge ${profile.display_name} (${profile.email || PROFILE_SCOPE_LABELS[profile.identity_scope]}) into ${selected.display_name} (${selected.email || PROFILE_SCOPE_LABELS[selected.identity_scope]})? Claims and linked identities will be combined. Future meetings will update ${selected.display_name}.`)) merge.mutate(selected);
  };

  return <section className="card" aria-label="Profile identities">
    <h3 className="section-title">Linked identities</h3>
    {profile.aliases.length > 0 && <ul style={{ marginLeft: 20, marginBottom: 12 }}>
      {profile.aliases.map(alias => <li key={alias.id}>{alias.display_name} · {alias.email || PROFILE_SCOPE_LABELS[alias.identity_scope]}</li>)}
    </ul>}
    {!mode ? <div style={{ display: 'flex', gap: 8 }}>
      <button className="btn" onClick={() => open('email')} disabled={disabled}>Link known email</button>
      <button className="btn" onClick={() => open('merge')} disabled={disabled}>Merge profile</button>
    </div> : <>
      {mode === 'email' ? <form onSubmit={event => { event.preventDefault(); if (email.trim()) link.mutate(); }}>
        <label className="form-label" htmlFor="profile-known-email">Known email</label>
        <input id="profile-known-email" className="input" type="email" required maxLength={320} value={email} onChange={event => setEmail(event.target.value)} />
        <p className="text-muted-sm">Link an email you know belongs to this person. Future meetings with that email will update this profile.</p>
        <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? 'Linking...' : 'Link email'}</button>
      </form> : <>
        <form className="search-bar" onSubmit={event => { event.preventDefault(); setQuery(queryText.trim()); setSelected(null); }}>
          <input aria-label="Find merge target" placeholder="Search profiles by name or email..." value={queryText} onChange={event => setQueryText(event.target.value)} maxLength={1000} />
          <button className="btn" type="submit">Find profiles</button>
        </form>
        {targets.error ? <p role="alert">Could not load merge targets. <button className="btn" onClick={() => targets.refresh()}>Retry</button></p> : <>
          <label className="form-label" htmlFor="profile-merge-target">Keep this profile</label>
          <select id="profile-merge-target" className="pagination-select" value={selected?.id || ''} disabled={targets.loading || saving}
            onChange={event => setSelected(targets.data?.items.find(item => item.id === event.target.value) || null)}>
            <option value="">{targets.loading ? 'Loading profiles...' : 'Select a profile'}</option>
            {targets.data?.items.filter(item => item.id !== profile.id).map(item => <option key={item.id} value={item.id}>{item.display_name} · {item.email || PROFILE_SCOPE_LABELS[item.identity_scope]}</option>)}
          </select>
          {selected && <p><Link to={`/profiles/${selected.id}`} target="_blank" rel="noopener noreferrer">Review {selected.display_name} before merging</Link></p>}
          <p className="text-muted-sm">Choose the profile to keep. Its evidence and the known identities from both profiles will be combined.</p>
          <button className="btn btn-primary" onClick={submitMerge} disabled={saving || targets.loading}>{saving ? 'Merging...' : 'Merge into selected profile'}</button>
        </>}
      </>}
      <button className="btn" style={{ marginTop: 8 }} onClick={() => { setMode(null); setNotice(null); }} disabled={saving}>Cancel</button>
    </>}
    {notice && <p role="alert">{notice}</p>}
  </section>;
}
