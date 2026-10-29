import { useEffect, useState } from 'react';
import { api, ApiError } from '../api';
import type { MeetingSummary } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { parseTags } from '../utils/tags';

interface Draft { text: string; revision: number; meetingRevision?: number; conflicted: boolean }

export function MeetingLabels({ meeting, onReload, onBusyChange }: {
  meeting: MeetingSummary; onReload: () => void; onBusyChange?: (busy: boolean) => void;
}) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const failed = (failure: Error) => {
    if (failure instanceof ApiError && failure.status === 409) {
      setDraft(previous => previous && { ...previous, conflicted: true });
      setNotice('This meeting or its labels changed. Review the latest information before saving again.'); onReload();
    } else setNotice('Could not update meeting labels. Try again.');
  };
  const save = useApiMutation({
    mutationFn: (labels: string[]) => api.meetings.updateLabels(meeting.id, {
      expected_revision: draft!.conflicted ? meeting.labels_revision || 0 : draft!.revision, labels,
      ...(draft!.meetingRevision !== undefined ? { expected_meeting_revision: draft!.conflicted ? meeting.revision : draft!.meetingRevision } : {}),
    }),
    onSuccess: () => { setDraft(null); setNotice(null); onReload(); }, onError: failed,
  });
  const suggest = useApiMutation({
    mutationFn: () => api.meetings.suggestLabels(meeting.id, meeting.labels_revision || 0),
    onSuccess: result => {
      setDraft({ text: result.labels.join(', '), revision: result.labels_revision, meetingRevision: result.meeting_revision, conflicted: false });
      setNotice('Suggestions are ready. Review the labels, then save.');
    }, onError: failure => {
      failed(failure);
      if (!(failure instanceof ApiError && failure.status === 409)) setNotice('Could not suggest labels. You can enter them yourself or try again.');
    },
  });
  const busy = save.loading || suggest.loading;
  useEffect(() => { onBusyChange?.(Boolean(draft) || busy); }, [draft, busy, onBusyChange]);
  const edit = () => { setNotice(null); setDraft({ text: (meeting.labels || []).join(', '), revision: meeting.labels_revision || 0, conflicted: false }); };
  return <section className="card" aria-label="Meeting purpose and topics">
    <div className="page-header profiles-header"><h3 className="section-title">Purpose and topics</h3>
      {!draft && <div className="flex-wrap">
        <button className="btn btn-sm" onClick={edit}>Edit labels</button>
        <button className="btn btn-sm" disabled={busy} onClick={() => { edit(); suggest.mutate(); }}>Suggest labels</button>
      </div>}
    </div>
    {draft ? <form onSubmit={event => {
      event.preventDefault(); if (busy) return;
      const labels = parseTags(draft.text);
      if (labels.length > 8 || labels.some(label => label.length > 50)) { setNotice('Use at most 8 labels, each 50 characters or fewer.'); return; }
      save.mutate(labels);
    }}>
      <label className="form-label" htmlFor="meeting-labels">Meeting labels</label>
      <input id="meeting-labels" className="input" disabled={busy} value={draft.text} maxLength={600}
        placeholder="product, roadmapping, paralign" onChange={event => setDraft({ ...draft, text: event.target.value })} />
      <p className="text-muted-sm">Describe the purpose, subject and relevant organization. These labels also appear on the meeting’s memories.</p>
      {draft.conflicted && <p className="text-muted-sm">Current labels: {(meeting.labels || []).join(', ') || 'None'}</p>}
      <div className="flex-wrap" style={{ marginTop: 12 }}>
        <button className="btn" disabled={busy}>{save.loading ? 'Saving...' : 'Save labels'}</button>
        <button className="btn" type="button" disabled={busy} onClick={() => suggest.mutate()}>{suggest.loading ? 'Suggesting...' : 'Suggest labels'}</button>
        <button className="btn" type="button" disabled={busy} onClick={() => { setDraft(null); setNotice(null); }}>Cancel</button>
      </div>
    </form> : <>
      {meeting.labels?.length ? <div className="flex-wrap">{meeting.labels.map(label => <span className="tag" key={label}>{label}</span>)}</div>
        : <p className="text-muted-sm">No topic labels yet. Add labels such as security, product, roadmapping, growth or operations.</p>}
      {meeting.labels_source && <p className="text-muted-sm" style={{ marginTop: 8 }}>{meeting.labels_source === 'human' ? 'Labels managed by you' : 'Suggested from meeting context'}</p>}
    </>}
    {notice && <p role="status" style={{ marginTop: 12 }}>{notice}</p>}
  </section>;
}
