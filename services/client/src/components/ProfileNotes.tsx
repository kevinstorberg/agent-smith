import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { ParticipantProfile, ProfileSectionKey, ProfileUpdateInput } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { formatProfileCoverage, PROFILE_SECTIONS } from '../utils/profileFields';

export function ProfileNotes({ profile, disabled, onBusyChange, onReload, sectionKeys, embedded = false }: {
  profile: ParticipantProfile; disabled: boolean; onBusyChange: (busy: boolean) => void; onReload: () => void;
  sectionKeys?: ProfileSectionKey[];
  embedded?: boolean;
}) {
  const [edit, setEdit] = useState<{ key: ProfileSectionKey; value: string; revision: number; refreshAfter: ParticipantProfile | null } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const latestProfile = useRef(profile);
  useEffect(() => { latestProfile.current = profile; }, [profile]);
  const save = useApiMutation({
    mutationFn: (body: ProfileUpdateInput) => api.profiles.update(profile.id, body),
    onSuccess: () => { setEdit(null); setNotice(null); onReload(); },
    onError: failure => {
      if (failure instanceof ApiError && failure.status === 409) {
        const refreshAfter = latestProfile.current;
        setEdit(previous => previous && { ...previous, refreshAfter });
        setNotice('This profile changed. Review the latest version before saving again.'); onReload();
      } else setNotice('Could not save this section. Your draft is retained.');
    },
  });
  const canSave = !save.loading && (!edit?.refreshAfter || profile !== edit.refreshAfter);
  useEffect(() => { onBusyChange(Boolean(edit) || save.loading); }, [edit, save.loading, onBusyChange]);
  return <section aria-label={sectionKeys?.length === 1 && sectionKeys[0] === 'overview' ? 'Profile overview' : 'Profile assessment'} className="profile-assessment-sections">
    {PROFILE_SECTIONS.filter(([key]) => sectionKeys ? sectionKeys.includes(key) : key !== 'relationships').map(([key, label]) => {
      const text = profile.section_notes?.[key];
      const source = profile.section_evidence?.[key];
      const human = source ? source.human === true : Object.hasOwn(profile.section_notes || {}, key);
      const observationCount = source?.claim_count ?? source?.claim_ids?.length ?? source?.coverage?.claim_count ?? 0;
      return <section className={embedded ? undefined : 'card'} aria-label={`${label} assessment`} key={key}>
        <div className="page-header profiles-header">{!embedded && <h3 className="section-title">{label}</h3>}
          {edit?.key !== key && <button className="btn btn-sm" disabled={disabled || Boolean(edit) || save.loading} onClick={() => {
            setNotice(null); setEdit({ key, value: text || '', revision: profile.revision, refreshAfter: null });
          }}>Edit {label.toLowerCase()}</button>}
        </div>
        {edit?.key === key ? <form onSubmit={event => {
          event.preventDefault(); if (!canSave) return;
          save.mutate({ expected_revision: edit.refreshAfter === null ? edit.revision : profile.revision, section_notes: { [key]: edit.value.trim() } });
        }}>
          <label className="form-label" htmlFor={`assessment-${key}`}>{label}</label>
          <textarea id={`assessment-${key}`} className="input" disabled={save.loading} rows={7} maxLength={4000}
            value={edit.value} onChange={event => setEdit({ ...edit, value: event.target.value })} />
          <p className="text-muted-sm">Your edits, including an empty section, are protected from automatic updates. You can allow automatic updates again later.</p>
          {edit.refreshAfter !== null && <div role="region" aria-label="Current saved section">
            <h4>Current saved section</h4>
            <p style={{ whiteSpace: 'pre-wrap' }}>{profile === edit.refreshAfter ? 'Waiting for refreshed information. Your draft is retained.' : text || 'Empty or no longer available from its source.'}</p>
            {profile === edit.refreshAfter && <button className="btn btn-sm" type="button" onClick={onReload}>Retry section refresh</button>}
          </div>}
          <div className="flex-wrap" style={{ marginTop: 12 }}>
            <button className="btn" disabled={!canSave}>{save.loading ? 'Saving...' : 'Save section'}</button>
            <button className="btn" type="button" disabled={save.loading} onClick={() => { setEdit(null); setNotice(null); }}>Cancel</button>
          </div>
        </form> : <>
          {text ? <div className="markdown-content"><ReactMarkdown>{text}</ReactMarkdown></div>
            : <p className="text-muted-sm">{human ? 'You have kept this section empty.' : 'There is not enough saved evidence to assess this section yet.'}</p>}
          <div className="flex-wrap" style={{ alignItems: 'center', marginTop: 12 }}>
            {human ? <>
              <span className="tag">Edited by you</span>
              <button className="btn btn-sm" disabled={disabled || Boolean(edit) || save.loading} onClick={() => save.mutate({
                expected_revision: profile.revision, allow_agent_sections: [key],
              })}>Allow automatic updates to {label.toLowerCase()}</button>
            </> : source && <span className="text-muted-sm">{source.status === 'insufficient_evidence' ? 'More evidence needed' : 'Updated automatically'}
              {source.coverage && ` · ${formatProfileCoverage(source.coverage)}`}</span>}
          </div>
          {observationCount > 0 && <p className="profile-evidence-link"><Link className="text-link" to={`/profiles/${profile.id}?tab=evidence`}>Supporting evidence ({observationCount})</Link></p>}
        </>}
      </section>;
    })}
    {notice && <p className="card" role="alert">{notice}</p>}
  </section>;
}
