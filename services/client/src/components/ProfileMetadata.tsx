import { useEffect, useState } from 'react';
import { api, ApiError } from '../api';
import type { ParticipantProfile, ProfileUpdateInput } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { parseTags } from '../utils/tags';
import { BadgeCell } from './table';
import { ProfileStar } from './ProfileStar';

interface Props {
  profile: ParticipantProfile;
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
  onReload: () => void;
}

export function ProfileMetadata({ profile, disabled, onBusyChange, onReload }: Props) {
  const [editing, setEditing] = useState(false);
  const [tags, setTags] = useState('');
  const [starred, setStarred] = useState(false);
  const [revision, setRevision] = useState(profile.revision);
  const [conflicted, setConflicted] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const update = useApiMutation({
    mutationFn: (body: ProfileUpdateInput) => api.profiles.update(profile.id, body),
    onSuccess: () => { setEditing(false); setNotice(null); onReload(); },
    onError: failure => {
      if (failure instanceof ApiError && failure.status === 409) {
        setConflicted(true);
        setNotice('This profile changed. Review the latest version and save again.');
        onReload();
      } else setNotice('Could not save profile tags or star. Try again.');
    },
  });
  useEffect(() => { onBusyChange(editing || update.loading); }, [editing, update.loading, onBusyChange]);

  const start = () => {
    setTags(profile.tags.join(', ')); setStarred(profile.starred); setRevision(profile.revision);
    setConflicted(false); setNotice(null); setEditing(true);
  };
  const save = () => {
    const parsed = parseTags(tags);
    if (parsed.length > 20 || parsed.some(tag => tag.length > 100)) {
      setNotice('Use at most 20 tags, each 100 characters or fewer.'); return;
    }
    update.mutate({ expected_revision: conflicted ? profile.revision : revision, tags: parsed, starred });
  };

  return <section aria-label="Profile tags and star" style={{ marginTop: 12 }}>
    {editing ? <>
      <label className="form-label" htmlFor="profile-tags">Tags</label>
      <input id="profile-tags" className="input" style={{ width: '100%' }} value={tags} onChange={event => setTags(event.target.value)} placeholder="Tags (comma-separated)" />
      <label style={{ display: 'block', marginTop: 8 }}><input type="checkbox" checked={starred} onChange={event => setStarred(event.target.checked)} /> Starred</label>
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button className="btn btn-primary" onClick={save} disabled={update.loading}>Save tags and star</button>
        <button className="btn" onClick={() => { setEditing(false); setNotice(null); }} disabled={update.loading}>Cancel</button>
      </div>
    </> : <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <ProfileStar name={profile.display_name} starred={profile.starred} disabled={disabled || update.loading}
        onClick={() => update.mutate({ expected_revision: profile.revision, starred: !profile.starred })} />
      <BadgeCell items={profile.tags} />
      <button className="btn btn-sm" onClick={start} disabled={disabled || update.loading}>Edit tags and star</button>
    </div>}
    {notice && <p role="alert">{notice}</p>}
  </section>;
}
