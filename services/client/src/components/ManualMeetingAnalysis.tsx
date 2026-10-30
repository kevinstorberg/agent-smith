import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { MeetingAnalysisCandidate, MeetingAnalysisInput, MeetingAnalysisReceipt, MeetingAnalysisScope } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { useManualAnalysisRequest } from '../hooks/useManualAnalysisRequest';
import { Pagination } from './Pagination';
import { DateCell } from './table';

const STAGES = { profile: 'Profiles', memory: 'Memories' };
const STATUS = { queued: 'Queued', running: 'Running', continued: 'Progress saved', done: 'Complete', failed: 'Needs attention' };
const STAGE_STATUS: Record<string, string> = { done: 'Complete', pending: 'Queued', running: 'Running', failed: 'Needs attention', not_imported: 'Not processed' };
const MATCHES: Record<string, string> = {
  participant_assignment: 'Assigned participant', identified_speaker: 'Identified speaker', transcript_speaker: 'Transcript speaker',
  attendee_email: 'Attendee email', attendee_name: 'Attendee name', speaker_name: 'Speaker name',
};
const selectedStages = (scope: MeetingAnalysisScope) => scope === 'both' ? ['profile', 'memory'] as const : scope === 'profiles' ? ['profile'] as const : ['memory'] as const;
const scopeLabel = (scope: MeetingAnalysisScope) => scope === 'both' ? 'Profiles and memories' : scope === 'profiles' ? 'Profiles' : 'Memories';
function dayBoundary(value: string, end: boolean): string {
  if (!value) return '';
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day, end ? 23 : 0, end ? 59 : 0, end ? 59 : 0, end ? 999 : 0).toISOString();
}
function analysisError(category: string, stage: 'profile' | 'memory', status: MeetingAnalysisReceipt['status']): string {
  if (['ManualAnalysisSuperseded', 'ManualAnalysisInputChanged'].includes(category)) return stage === 'profile'
    ? 'Saved meeting context or the target profile changed. Review speaker assignments and confirm a fresh profile analysis.'
    : 'Saved meeting context changed. The memory checkpoint is kept. Review the meeting and linked job before resuming.';
  if (category === 'ManualAnalysisJobUnavailable') return 'Enable or configure the linked job for this meeting connection. Your request and saved progress are kept.';
  if (category === 'ProfileRevisionConflict') return 'The profile changed while analysis was saving. Resume unfinished analysis to use the current profile. Your edits stay protected.';
  if (category.toLowerCase().includes('timeout')) return `This attempt reached its time limit. Saved progress is kept. ${status === 'failed' ? 'Resume unfinished analysis to continue.' : 'The next job run continues from its checkpoint.'}`;
  return 'This analysis needs attention. Saved progress is kept. Check the linked job before resuming.';
}

function AnalysisProgress({ receipt }: { receipt: MeetingAnalysisReceipt }) {
  return <div className="manual-analysis-progress">
    <p role="status"><strong>{STATUS[receipt.status]}</strong> · {scopeLabel(receipt.scope)} · {receipt.items.length} {receipt.items.length === 1 ? 'meeting' : 'meetings'}</p>
    {receipt.items.map(item => <article key={item.meeting_id} className="manual-analysis-meeting">
      <h4><Link className="text-link" to={`/meetings/${item.meeting_id}`} target="_blank" rel="noopener noreferrer">{item.title || 'Untitled meeting'}</Link></h4>
      {(['profile', 'memory'] as const).map(key => {
        const stage = item.stages[key];
        if (!stage) return null;
        const progress = stage.progress;
        return <div key={key} className="manual-analysis-stage">
          <p><strong>{STAGES[key]}</strong> · {STATUS[stage.status]}{stage.waiting_for === 'job' ? ' · Waiting for an eligible job' : ''}</p>
          {progress.total_units !== null && progress.total_units > 0 && <>
            <progress aria-label={`${STAGES[key]} analysis progress`} max={progress.total_units} value={Math.min(progress.processed_units, progress.total_units)} />
            <p className="text-muted-sm">{progress.processed_units} of {progress.total_units} transcript sections analyzed</p>
          </>}
          <p className="text-muted-sm">{progress.staged_count} candidates saved · {progress.saved_count} {key === 'profile' ? 'profiles updated' : 'memories published'}</p>
          {stage.status === 'continued' && <p className="text-muted-sm">The next run resumes saved progress.</p>}
          {progress.next_attempt_at && stage.status !== 'done' && <div className="manual-analysis-metadata text-muted-sm"><span>Next eligible attempt:</span><DateCell date={progress.next_attempt_at} format="long" /></div>}
          {stage.error_type && <><p role="alert">{analysisError(stage.error_type, key, stage.status)}</p><details className="text-muted-sm"><summary>Technical details</summary><p>{stage.error_type}</p></details></>}
          <Link className="text-link" to={stage.waiting_for === 'job' ? '/jobs' : `/jobs/${stage.job_id}?tab=executions`} target="_blank" rel="noopener noreferrer">{stage.waiting_for === 'job' ? 'Configure analysis jobs' : stage.job_name}</Link>
        </div>;
      })}
    </article>)}
  </div>;
}

function MeetingSelection({ profile, meetingId, notice, onConfirm }: {
  profile?: { id: string; display_name: string }; meetingId?: string;
  notice: string | null; onConfirm: (input: MeetingAnalysisInput) => void;
}) {
  const [related, setRelated] = useState(Boolean(profile));
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('');
  const [after, setAfter] = useState('');
  const [before, setBefore] = useState('');
  const [searchTranscript, setSearchTranscript] = useState(false);
  const [offset, setOffset] = useState(0);
  const [scope, setScope] = useState<MeetingAnalysisScope>('profiles');
  const [selection, setSelection] = useState<Map<string, MeetingAnalysisCandidate>>(new Map());
  const [target, setTarget] = useState<{ id: string; expected_revision: number } | undefined>();
  const [reviewing, setReviewing] = useState(false);
  const fixedSelection = useRef(false);
  const profileId = profile?.id;
  const debouncedQuery = useDebouncedValue(query.trim());
  const debouncedSource = useDebouncedValue(source.trim());
  const datesInvalid = Boolean(after && before && after > before);
  const criteriaPending = debouncedQuery !== query.trim() || debouncedSource !== source.trim();
  const read = useCallback(() => datesInvalid ? Promise.reject(new Error('The end date must be on or after the start date.')) : api.meetingAnalysis.candidates({
    ...(profileId ? { profile_id: profileId } : {}), ...(meetingId ? { meeting_id: meetingId } : {}),
    related, q: debouncedQuery, search_transcript: searchTranscript && Boolean(debouncedQuery),
    source: debouncedSource, after: dayBoundary(after, false), before: dayBoundary(before, true), limit: 10, offset,
  }), [profileId, meetingId, related, debouncedQuery, searchTranscript, debouncedSource, after, before, offset, datesInvalid]);
  const { data, loading, error, refresh } = useApiRead(read);
  useEffect(() => { setOffset(0); }, [related, debouncedQuery, searchTranscript, debouncedSource, after, before]);
  useEffect(() => {
    if (data && !loading && !error && data.total > 0 && offset >= data.total) setOffset(Math.floor((data.total - 1) / 10) * 10);
  }, [data, loading, error, offset]);
  const stages = selectedStages(scope);
  const blocked = (item: MeetingAnalysisCandidate) => {
    const unavailable = stages.map(stage => item.stages[stage]).find(stage => !stage.can_reanalyze);
    return unavailable ? unavailable.blocked_reason || 'This analysis is not available for this meeting.' : null;
  };
  useEffect(() => {
    const item = data?.items.find(candidate => candidate.id === meetingId);
    if (!item || fixedSelection.current || !selectedStages(scope).every(stage => item.stages[stage].can_reanalyze)) return;
    fixedSelection.current = true;
    setSelection(new Map([[item.id, item]]));
  }, [meetingId, data, scope]);
  const identityChanged = Boolean(profile && data?.profile && data.profile.id !== profile.id);
  const canReview = selection.size > 0 && !loading && !error && !criteriaPending && !datesInvalid && !identityChanged
    && [...selection.values()].every(item => !blocked(item));
  const toggle = (item: MeetingAnalysisCandidate) => {
    if (loading || criteriaPending || identityChanged) return;
    setReviewing(false);
    if (!selection.has(item.id) && data?.profile && !target) setTarget({ id: data.profile.id, expected_revision: data.profile.revision });
    setSelection(previous => {
      const next = new Map(previous);
      if (next.has(item.id)) next.delete(item.id); else if (next.size < 10 && !blocked(item)) next.set(item.id, item);
      return next;
    });
  };
  const submit = () => {
    if (!canReview || !reviewing) return;
    onConfirm({ request_id: crypto.randomUUID(), confirmed: true, scope,
      ...(profile && scope !== 'memories' && target ? { target_profile: target } : {}),
      meetings: [...selection.values()].map(item => ({ id: item.id, expected: { ...item.expected } })),
    });
  };
  return <>
    {notice && <p role="alert">{notice}</p>}
    {reviewing ? <section aria-label="Confirm meeting analysis" className="manual-analysis-confirm">
      <h4>Review your selection</h4>
      <p><strong>{selection.size} {selection.size === 1 ? 'meeting' : 'meetings'}</strong> · {profile ? `Profiles for ${profile.display_name}${scope === 'both' ? ' · Memories from the full meetings' : ''}` : scopeLabel(scope)}</p>
      <ul>{[...selection.values()].map(item => <li key={item.id}>{item.title || 'Untitled meeting'} · {item.source_name}</li>)}</ul>
      <p>This starts one new analysis pass using the selected saved transcripts. Your configured models incur normal generation costs.</p>
      <p className="text-muted-sm">Your profile edits stay protected. Existing memories are kept; memory analysis adds new information. Scheduled jobs will not repeat this review.</p>
      <div className="flex-wrap"><button className="btn btn-primary" disabled={!canReview} onClick={submit}>Confirm analysis</button><button className="btn" onClick={() => setReviewing(false)}>Back to selection</button></div>
    </section> : <>
      {profile && <div className="sub-tabs" role="group" aria-label="Meeting candidates">
        <button className={related ? 'active' : ''} aria-pressed={related} onClick={() => setRelated(true)}>Related meetings</button>
        <button className={!related ? 'active' : ''} aria-pressed={!related} onClick={() => setRelated(false)}>All saved meetings</button>
      </div>}
      {!meetingId && <>
        <div className="manual-analysis-filters">
          <label className="form-label">Search meetings<input className="input" value={query} maxLength={1000} placeholder="Title or summary" onChange={event => setQuery(event.target.value)} /></label>
          <label className="form-label">Connection<input className="input" value={source} maxLength={100} placeholder="All connections" onChange={event => setSource(event.target.value)} /></label>
          <label className="form-label">From<input className="input" type="date" value={after} onChange={event => setAfter(event.target.value)} /></label>
          <label className="form-label">Through<input className="input" type="date" value={before} onChange={event => setBefore(event.target.value)} /></label>
        </div>
        <label className="checkbox-label"><input className="form-checkbox" type="checkbox" checked={searchTranscript} onChange={event => setSearchTranscript(event.target.checked)} />Include saved transcript text in search</label>
      </>}
      <div className="manual-analysis-scope"><label className="form-label" htmlFor="manual-analysis-scope">Analyze</label><select id="manual-analysis-scope" className="input" value={scope} onChange={event => { setScope(event.target.value as MeetingAnalysisScope); setReviewing(false); }}>
        <option value="profiles">Profiles{profile ? ` for ${profile.display_name}` : ''}</option>
        {!profile && <option value="memories">Memories</option>}
        <option value="both">Profiles and memories</option>
      </select></div>
      {profile && scope === 'both' && <p className="text-muted-sm">Profiles update only {profile.display_name}. Memories capture useful information from each full meeting.</p>}
      <p className="text-muted-sm">Select up to 10 saved meetings. {profile ? 'Attendee matches help find a meeting; profile analysis requires this person to be assigned to transcript statements.' : 'Profile analysis uses identified transcript statements. Resume unfinished work from the meeting instead.'}</p>
      {datesInvalid && <p role="alert">The end date must be on or after the start date.</p>}
      {identityChanged && <p role="alert">This profile was merged or changed identity. Reload its current profile before requesting analysis.</p>}
      {error && <div role="alert"><p>Could not load meetings: {error}</p><button className="btn btn-sm" onClick={() => refresh()}>Retry meeting search</button></div>}
      {loading && <p role="status">Loading meetings...</p>}
      {!loading && !error && !data?.items.length && <p>No saved meetings match these filters. {profile && related ? 'Try All saved meetings or adjust your search.' : 'Adjust your search or save a meeting transcript first.'}</p>}
      <div className="manual-analysis-candidates" aria-label="Saved meeting candidates">
        {data?.items.map(item => {
          const reason = blocked(item);
          return <article key={item.id} className="manual-analysis-meeting">
            <label className="checkbox-label manual-analysis-candidate-title"><input className="form-checkbox" type="checkbox" aria-label={`Select ${item.title || 'Untitled meeting'}`} checked={selection.has(item.id)} disabled={loading || criteriaPending || identityChanged || (!selection.has(item.id) && (Boolean(reason) || selection.size >= 10))} onChange={() => toggle(item)} /><strong>{item.title || 'Untitled meeting'}</strong></label>
            <div className="manual-analysis-metadata text-muted-sm"><span>{item.source_name}</span><span>·</span>{item.meeting_start ? <DateCell date={item.meeting_start} /> : <span>Date unavailable</span>}{item.match_reasons.length > 0 && <span>· {item.match_reasons.map(value => MATCHES[value] || value.replaceAll('_', ' ')).join(', ')}</span>}</div>
            <p className="text-muted-sm">Profiles: {STAGE_STATUS[item.stages.profile.status] || item.stages.profile.status} · Memories: {STAGE_STATUS[item.stages.memory.status] || item.stages.memory.status}</p>
            {reason && <p className="text-muted-sm">{reason}</p>}
            <Link className="text-link" to={`/meetings/${item.id}${profile && !item.attribution_ready ? '#meeting-participants' : ''}`} target="_blank" rel="noopener noreferrer">{profile && !item.attribution_ready ? 'Assign transcript speakers' : reason && stages.some(stage => item.stages[stage].status !== 'done') ? 'Resume unfinished work' : 'View meeting'}</Link>
          </article>;
        })}
      </div>
      {!meetingId && data && <Pagination total={data.total} limit={10} offset={offset} onPageChange={setOffset} disabled={loading || criteriaPending} />}
      <div className="manual-analysis-selection"><span>{selection.size} of 10 selected</span>
        {selection.size > 0 && <button className="btn btn-sm" onClick={() => { setSelection(new Map()); setTarget(undefined); }}>Clear selection</button>}
        <button className="btn btn-primary" disabled={!canReview} onClick={() => setReviewing(true)}>Review selection</button>
      </div>
      {[...selection.values()].filter(item => blocked(item)).map(item => <p key={item.id} role="alert">{item.title}: {blocked(item)} Remove it from your selection or choose another output.</p>)}
    </>}
  </>;
}

export function ManualMeetingAnalysis({ profile, meetingId, disabled = false, onChanged, onBusyChange }: {
  profile?: { id: string; display_name: string }; meetingId?: string; disabled?: boolean;
  onChanged: () => void; onBusyChange?: (busy: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  const request = useManualAnalysisRequest(onChanged);
  const { receipt, frozen, saving, reading, notice, expired } = request;
  useEffect(() => {
    if (open && dialog.current && !dialog.current.open) dialog.current.showModal();
    if (!open && wasOpen.current) trigger.current?.focus();
    wasOpen.current = open;
    onBusyChange?.(open || saving);
  }, [open, saving, onBusyChange]);
  const close = () => setOpen(false);
  return <>
    <button ref={trigger} className="btn btn-sm" disabled={disabled && !receipt && !frozen} onClick={() => setOpen(true)}>{receipt || frozen || request.requestId ? 'View analysis progress' : profile ? 'Review past meetings' : 'Reanalyze completed...'}</button>
    {open && <dialog ref={dialog} className="manual-analysis-dialog" aria-label={receipt || frozen || request.requestId ? 'Meeting analysis progress' : profile ? 'Review past meetings' : 'Reanalyze saved meeting'} onCancel={event => { event.preventDefault(); close(); }}>
      <div className="page-header profiles-header"><h3 className="section-title">{receipt || frozen || request.requestId ? 'Meeting analysis' : profile ? 'Review past meetings' : 'Reanalyze saved meeting'}</h3><button className="btn btn-sm" onClick={close}>Close</button></div>
      {receipt ? <>
        <AnalysisProgress receipt={receipt} />
        <p className="text-muted-sm">Your existing jobs run this request in the background. Closing this view will not stop it.</p>
        {expired && <p role="status">Automatic monitoring paused after 30 minutes. The request can still run. Refresh its status when you return.</p>}
        {notice && <p role="alert">{notice}</p>}
        <div className="flex-wrap"><button className="btn" disabled={reading || saving} onClick={request.refresh}>{reading ? 'Refreshing...' : 'Refresh status'}</button>
          {receipt.status === 'failed' && <button className="btn" disabled={saving} onClick={request.resume}>{saving ? 'Queuing...' : 'Resume unfinished analysis'}</button>}
          {['done', 'failed'].includes(receipt.status) && <button className="btn" disabled={saving} onClick={request.reset}>Review another selection</button>}
        </div>
      </> : frozen ? <>
        <p>{scopeLabel(frozen.scope)} · {frozen.meetings.length} selected {frozen.meetings.length === 1 ? 'meeting' : 'meetings'}</p>
        <p role={notice ? 'alert' : 'status'}>{notice || 'Queuing your analysis request...'}</p>
        <button className="btn" disabled={saving} onClick={() => request.submit(frozen)}>{saving ? 'Queuing...' : 'Retry same request'}</button>
      </> : request.requestId ? <>
        <p role={notice ? 'alert' : 'status'}>{notice || 'Loading analysis progress...'}</p><button className="btn" disabled={reading} onClick={request.refresh}>Refresh status</button>
        <button className="btn" onClick={request.reset}>Back to meeting selection</button>
      </> : <MeetingSelection profile={profile} meetingId={meetingId} notice={notice} onConfirm={request.submit} />}
    </dialog>}
  </>;
}
