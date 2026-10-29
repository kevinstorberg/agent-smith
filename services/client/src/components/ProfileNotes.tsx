import { useEffect, useState } from 'react';
import { api, ApiError } from '../api';
import type { ParticipantProfile, ProfileSectionNotes } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';

const SECTIONS: [keyof ProfileSectionNotes, string][] = [['drivers', 'Drivers'], ['strengths', 'Strengths'], ['development_areas', 'Development areas']];

export function ProfileNotes({ profile, disabled, onBusyChange, onReload }: {
  profile: ParticipantProfile; disabled: boolean; onBusyChange: (busy: boolean) => void; onReload: () => void;
}) {
  const [edit, setEdit] = useState<{ key: keyof ProfileSectionNotes; value: string; revision: number; conflicted: boolean } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const save = useApiMutation({
    mutationFn: () => api.profiles.update(profile.id, { expected_revision: edit!.conflicted ? profile.revision : edit!.revision, section_notes: { [edit!.key]: edit!.value.trim() } }),
    onSuccess: () => { setEdit(null); setNotice(null); onReload(); },
    onError: failure => {
      if (failure instanceof ApiError && failure.status === 409) {
        setEdit(previous => previous && { ...previous, conflicted: true });
        setNotice('This profile changed. Review the latest version and save your note again.'); onReload();
      } else setNotice('Could not save your note. Try again.');
    },
  });
  useEffect(() => { onBusyChange(Boolean(edit) || save.loading); }, [edit, save.loading, onBusyChange]);
  return <section aria-label="Your profile notes">
    <h3 className="section-title">Your notes</h3>
    <div className="profile-notes-grid">{SECTIONS.map(([key, label]) => <section className="card" aria-label={`${label} notes`} key={key}>
      <h3>{label}</h3>
      {edit?.key === key ? <form onSubmit={event => { event.preventDefault(); if (!save.loading) save.mutate(); }}>
        <label className="form-label" htmlFor={`notes-${key}`}>Your {label.toLowerCase()} notes</label>
        <textarea id={`notes-${key}`} className="input" disabled={save.loading} rows={5} maxLength={4000} value={edit.value} onChange={event => setEdit({ ...edit, value: event.target.value })} />
        <div className="flex-wrap" style={{ marginTop: 8 }}>
          <button className="btn" disabled={save.loading}>{save.loading ? 'Saving...' : 'Save note'}</button>
          <button className="btn" type="button" disabled={save.loading} onClick={() => { setEdit(null); setNotice(null); }}>Cancel</button>
        </div>
      </form> : <>
        <p style={{ whiteSpace: 'pre-wrap', marginBottom: 12 }}>{profile.section_notes?.[key] || 'No notes added.'}</p>
        <button className="btn btn-sm" disabled={disabled || Boolean(edit)} onClick={() => { setNotice(null); setEdit({ key, value: profile.section_notes?.[key] || '', revision: profile.revision, conflicted: false }); }}>Edit {label.toLowerCase()} notes</button>
      </>}
    </section>)}</div>
    {notice && <p className="card" role="alert">{notice}</p>}
  </section>;
}
