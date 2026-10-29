import { useEffect, useRef, useState } from 'react';
import type { Ref } from 'react';
import { api, ApiError } from '../api';
import type { ParticipantProfile, ProfileUpdateInput, ProfileMetadataFields } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { parseTags } from '../utils/tags';
import { BadgeCell } from './table';
import { ProfileStar } from './ProfileStar';
import { Link } from 'react-router';
import { PROFILE_METADATA_FIELDS as METADATA_FIELDS } from '../utils/profileFields';

interface Props {
  profile: ParticipantProfile;
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
  onReload: () => void;
  editing?: boolean;
  onEditingChange?: (editing: boolean) => void;
  onSavingChange?: (saving: boolean) => void;
  formRef?: Ref<HTMLFormElement>;
}

export function ProfileMetadata({ profile, disabled, onBusyChange, onReload, editing: controlledEditing, onEditingChange, onSavingChange, formRef }: Props) {
  const [localEditing, setLocalEditing] = useState(false);
  const editing = controlledEditing ?? localEditing;
  const setEditing = (value: boolean) => {
    if (controlledEditing === undefined) setLocalEditing(value);
    else onEditingChange?.(value);
  };
  const previousEditing = useRef(false);
  const [name, setName] = useState('');
  const [tags, setTags] = useState('');
  const [starred, setStarred] = useState(false);
  const [revision, setRevision] = useState(profile.revision);
  const [conflicted, setConflicted] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [nicknames, setNicknames] = useState('');
  const [nicknamesChanged, setNicknamesChanged] = useState(false);
  const [metadata, setMetadata] = useState<ProfileMetadataFields>({});
  const [metadataChanged, setMetadataChanged] = useState<(keyof ProfileMetadataFields)[]>([]);
  const update = useApiMutation({
    mutationFn: (body: ProfileUpdateInput) => api.profiles.update(profile.id, body),
    onSuccess: () => { setEditing(false); setNotice(null); onReload(); },
    onError: failure => {
      if (failure instanceof ApiError && failure.status === 409) {
        setConflicted(true);
        setNotice('This profile changed. Review the latest version and save again.');
        onReload();
      } else setNotice('Could not save this profile. Try again.');
    },
  });
  useEffect(() => { onBusyChange(editing || update.loading); }, [editing, update.loading, onBusyChange]);
  useEffect(() => { onSavingChange?.(update.loading); }, [update.loading, onSavingChange]);

  useEffect(() => {
    if (editing && !previousEditing.current) {
      setName(profile.display_name);
      setNicknames((profile.nicknames || []).join(', ')); setNicknamesChanged(false);
      setMetadata({ ...profile.metadata }); setMetadataChanged([]);
      setTags(profile.tags.join(', ')); setStarred(profile.starred); setRevision(profile.revision);
      setConflicted(false); setNotice(null);
    }
    previousEditing.current = editing;
  }, [editing, profile]);
  const save = () => {
    if (update.loading || disabled) return;
    if (!name.trim()) { setNotice('A profile name is required.'); return; }
    const parsed = parseTags(tags);
    if (parsed.length > 20 || parsed.some(tag => tag.length > 100)) {
      setNotice('Use at most 20 tags, each 100 characters or fewer.'); return;
    }
    const nicknameKeys = new Set<string>();
    const aliases = parseTags(nicknames).filter(nickname => {
      const key = nickname.toLocaleLowerCase();
      if (nicknameKeys.has(key)) return false;
      nicknameKeys.add(key); return true;
    });
    if (nicknamesChanged && (aliases.length > 20 || aliases.some(alias => alias.length > 100))) {
      setNotice('Use at most 20 nicknames, each 100 characters or fewer.'); return;
    }
    update.mutate({ expected_revision: conflicted ? profile.revision : revision, display_name: name.trim(), tags: parsed, starred,
      ...(nicknamesChanged ? { nicknames: aliases } : {}),
      ...(metadataChanged.length ? { metadata: Object.fromEntries(metadataChanged.map(key => [key, (metadata[key] || '').trim()])) } : {}),
    });
  };
  const changeMetadata = (key: keyof ProfileMetadataFields, value: string) => {
    setMetadata(previous => ({ ...previous, [key]: value }));
    setMetadataChanged(previous => previous.includes(key) ? previous : [...previous, key]);
  };

  return <section aria-label="Profile details" style={{ marginTop: 12 }}>
    {editing ? <form ref={formRef} onSubmit={event => { event.preventDefault(); save(); }}>
      <label className="form-label" htmlFor="profile-name">Name</label>
      <input id="profile-name" className="input" disabled={update.loading} style={{ marginBottom: 12 }} maxLength={200} value={name} onChange={event => setName(event.target.value)} />
      <label className="form-label" htmlFor="profile-nicknames">Nicknames</label>
      <input id="profile-nicknames" className="input" disabled={update.loading} style={{ marginBottom: 12 }} value={nicknames} maxLength={2200} placeholder="Comma-separated nicknames"
        onChange={event => { setNicknames(event.target.value); setNicknamesChanged(true); }} />
      <div className="profile-field-grid">
        {METADATA_FIELDS.map(({ key, label, type }) => <div key={key}>
          <label className="form-label" htmlFor={`profile-${key}`}>{label}</label>
          <input id={`profile-${key}`} className="input" disabled={update.loading} type={type || 'text'} maxLength={200} value={metadata[key] || ''} onChange={event => changeMetadata(key, event.target.value)} />
        </div>)}
      </div>
      <label className="form-label" htmlFor="profile-other">Other</label>
      <textarea id="profile-other" className="input" disabled={update.loading} rows={3} maxLength={4000} value={metadata.other || ''} onChange={event => changeMetadata('other', event.target.value)} />
      <p className="text-muted-sm">All fields are optional. Your changes take priority over future persona updates. Supervisor text does not create a linked relationship.</p>
      <label className="form-label" htmlFor="profile-tags">Tags</label>
      <input id="profile-tags" className="input" disabled={update.loading} style={{ width: '100%' }} value={tags} onChange={event => setTags(event.target.value)} placeholder="Tags (comma-separated)" />
      <label style={{ display: 'block', marginTop: 8 }}><input type="checkbox" disabled={update.loading} checked={starred} onChange={event => setStarred(event.target.checked)} /> Starred</label>
      {controlledEditing === undefined && <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button className="btn" type="submit" disabled={update.loading}>Save profile</button>
        <button className="btn" type="button" onClick={() => { setEditing(false); setNotice(null); }} disabled={update.loading}>Cancel</button>
      </div>}
    </form> : <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <ProfileStar name={profile.display_name} starred={profile.starred} disabled={disabled || update.loading}
        onClick={() => update.mutate({ expected_revision: profile.revision, starred: !profile.starred })} />
      <BadgeCell items={profile.tags} />
      {controlledEditing === undefined && <button className="btn btn-sm" onClick={() => setEditing(true)} disabled={disabled || update.loading}>Edit profile</button>}
    </div>}
    {!editing && <>
      {Boolean(profile.nicknames?.length) && <p className="text-muted-sm" style={{ marginTop: 8 }}>Also known as: {profile.nicknames!.join(', ')}</p>}
      {Object.keys(profile.metadata || {}).length > 0 && <details style={{ marginTop: 12 }}><summary>About this person</summary>
        <dl className="profile-details">{[...METADATA_FIELDS, { key: 'other' as const, label: 'Other' }].filter(field => profile.metadata?.[field.key]).map(field => {
          const source = profile.metadata_provenance?.[field.key];
          return <div key={field.key}>
            <dt>{field.label}</dt><dd style={{ whiteSpace: 'pre-wrap' }}>{profile.metadata![field.key]}
              {source?.human && <p className="text-muted-sm">Edited by you</p>}
              {source && 'meeting_id' in source && <details><summary>Meeting source</summary>
                {source.evidence.map((evidence, index) => <blockquote key={`${evidence.segment_id}-${index}`}>{evidence.quote}</blockquote>)}
                <Link className="text-link" to={`/meetings/${encodeURIComponent(source.meeting_id)}#meeting-transcript`}>View source meeting</Link>
              </details>}
            </dd>
          </div>;
        })}</dl>
      </details>}
    </>}
    {notice && <p role="alert">{notice}</p>}
  </section>;
}
