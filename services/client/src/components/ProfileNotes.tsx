import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Link } from 'react-router';
import { api, ApiError } from '../api';
import type { ParticipantProfile, ProfileSectionKey, ProfileUpdateInput } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { formatProfileCoverage, PROFILE_SECTIONS } from '../utils/profileFields';

export function ProfileNotes({ profile, disabled, onBusyChange, onReload }: {
  profile: ParticipantProfile; disabled: boolean; onBusyChange: (busy: boolean) => void; onReload: () => void;
}) {
  const [edit, setEdit] = useState<{ key: ProfileSectionKey; value: string; revision: number; conflicted: boolean } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const save = useApiMutation({
    mutationFn: (body: ProfileUpdateInput) => api.profiles.update(profile.id, body),
    onSuccess: () => { setEdit(null); setNotice(null); onReload(); },
    onError: failure => {
      if (failure instanceof ApiError && failure.status === 409) {
        setEdit(previous => previous && { ...previous, conflicted: true });
        setNotice('This profile changed. Review the latest version before saving again.'); onReload();
      } else setNotice('Could not save this section. Your draft is retained.');
    },
  });
  useEffect(() => { onBusyChange(Boolean(edit) || save.loading); }, [edit, save.loading, onBusyChange]);
  return <section aria-label="Profile assessment" className="profile-assessment-sections">
    {PROFILE_SECTIONS.map(([key, label]) => {
      const text = profile.section_notes?.[key];
      const source = profile.section_evidence?.[key];
      const observations = profile.claims.filter(claim => claim.status !== 'rejected' && source?.claim_ids?.includes(claim.id));
      return <section className="card" aria-label={`${label} assessment`} key={key}>
        <div className="page-header profiles-header"><h3 className="section-title">{label}</h3>
          {edit?.key !== key && <button className="btn btn-sm" disabled={disabled || Boolean(edit) || save.loading} onClick={() => {
            setNotice(null); setEdit({ key, value: text || '', revision: profile.revision, conflicted: false });
          }}>Edit {label.toLowerCase()}</button>}
        </div>
        {edit?.key === key ? <form onSubmit={event => {
          event.preventDefault(); if (save.loading) return;
          save.mutate({ expected_revision: edit.conflicted ? profile.revision : edit.revision, section_notes: { [key]: edit.value.trim() } });
        }}>
          <label className="form-label" htmlFor={`assessment-${key}`}>{label}</label>
          <textarea id={`assessment-${key}`} className="input" disabled={save.loading} rows={7} maxLength={4000}
            value={edit.value} onChange={event => setEdit({ ...edit, value: event.target.value })} />
          <p className="text-muted-sm">Your edits, including an empty section, are protected from automatic updates. You can allow automatic updates again later.</p>
          {edit.conflicted && <details><summary>Current saved section</summary><p style={{ whiteSpace: 'pre-wrap' }}>{text || 'Empty'}</p></details>}
          <div className="flex-wrap" style={{ marginTop: 12 }}>
            <button className="btn" disabled={save.loading}>{save.loading ? 'Saving...' : 'Save section'}</button>
            <button className="btn" type="button" disabled={save.loading} onClick={() => { setEdit(null); setNotice(null); }}>Cancel</button>
          </div>
        </form> : <>
          {text ? <div className="markdown-content"><ReactMarkdown>{text}</ReactMarkdown></div>
            : <p className="text-muted-sm">{source?.human ? 'You have kept this section empty.' : 'There is not enough saved evidence to assess this section yet.'}</p>}
          <div className="flex-wrap" style={{ alignItems: 'center', marginTop: 12 }}>
            {source?.human ? <>
              <span className="tag">Edited by you</span>
              <button className="btn btn-sm" disabled={disabled || Boolean(edit) || save.loading} onClick={() => save.mutate({
                expected_revision: profile.revision, allow_agent_sections: [key],
              })}>Allow automatic updates to {label.toLowerCase()}</button>
            </> : source && <span className="text-muted-sm">{source.status === 'insufficient_evidence' ? 'More evidence needed' : 'Updated automatically'}
              {source.coverage && ` · ${formatProfileCoverage(source.coverage)}`}</span>}
          </div>
          {observations.length > 0 && <details style={{ marginTop: 12 }}><summary>Supporting evidence ({observations.length})</summary>
            {observations.map(claim => <article key={claim.id} style={{ marginTop: 12 }}>
              <p>{claim.status === 'corrected' ? claim.correction?.content || claim.content : claim.content}</p>
              <p className="text-muted-sm">{claim.confidence} confidence · {claim.epistemic === 'inference' ? 'Hypothesis' : claim.epistemic === 'self_report' ? 'Self-reported' : 'Observed'}</p>
              <Link className="text-link" to={`/meetings/${claim.meeting_id}#meeting-transcript`}>Source meeting</Link>
            </article>)}
          </details>}
        </>}
      </section>;
    })}
    {notice && <p className="card" role="alert">{notice}</p>}
  </section>;
}
