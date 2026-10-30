import { useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { MeetingGeneration, MeetingProcessingState } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { ManualMeetingAnalysis } from './ManualMeetingAnalysis';
import { MeetingGenerationProgress } from './MeetingGenerationProgress';

const LABELS: Record<string, string> = { not_imported: 'Not queued', pending: 'Queued', running: 'Running', capturing: 'Running', ready: 'Complete', done: 'Complete', blocked: 'Waiting for transcript', failed: 'Needs attention', unavailable: 'Unavailable', unsupported: 'Unsupported', deleted: 'Deleted', legacy: 'Not reviewed' };

export function MeetingProcessing({ meetingId, transcript, memories, personas, speakers, onChanged, disabled = false }: {
  meetingId: string; transcript: MeetingProcessingState['transcript'] | null; memories: MeetingGeneration | null; personas: MeetingGeneration | null;
  speakers?: MeetingProcessingState['speakers'] | null; onChanged: () => void; disabled?: boolean;
}) {
  const [notice, setNotice] = useState<string | null>(null);
  const process = useApiMutation({ mutationFn: () => api.meetings.process(meetingId),
    onSuccess: result => { setNotice(result.status === 'done' ? 'Both workflows are complete.' : 'Missing work is queued for your meeting and persona jobs. Saved progress and completed outputs are preserved.'); onChanged(); },
    onError: () => setNotice('Could not queue processing. Try again.'),
  });
  const retry = useApiMutation({ mutationFn: (stage: 'memories' | 'profiles') => stage === 'memories' ? api.meetings.retryMemories(meetingId) : api.meetings.retryProfiles(meetingId),
    onSuccess: () => { setNotice('Retry queued. Completed work is preserved.'); onChanged(); }, onError: () => setNotice('Could not queue this retry. Try again.'),
  });
  const loaded = Boolean(transcript && memories && personas);
  const done = transcript?.status === 'ready' && memories?.status === 'done' && personas?.status === 'done';
  const running = transcript?.status === 'capturing' || speakers?.status === 'running' || memories?.status === 'running' || personas?.status === 'running';
  const resumable = memories?.progress?.processed_units || personas?.progress?.processed_units || transcript?.status === 'pending' || memories?.status === 'pending' || personas?.status === 'pending';
  return <section className="meeting-processing" aria-label="Meeting processing">
    <div className="meeting-processing-summary">
      <div className="flex-wrap meeting-stage-badges">{[['Transcript', '#meeting-transcript', transcript], ['Speakers', '#meeting-participants', speakers], ['Memories', '#meeting-memories', memories], ['Profiles', '#meeting-profiles', personas]].map(([label, href, result]) => {
        const stage = result as { status: string; progress?: MeetingGeneration['progress'] } | null | undefined;
        const statusLabel = stage?.status === 'pending' && (stage.progress?.processed_units ?? 0) > 0 ? 'Progress saved' : stage ? LABELS[stage.status] || stage.status : 'Loading...';
        return <a className={`tag text-link${stage?.status === 'failed' ? ' tag-danger' : ''}`} key={label as string} href={href as string}>{label as string}: {statusLabel}</a>;
      })}</div>
      <div className="flex-wrap">{done && (speakers?.status === 'failed' || speakers?.status === 'legacy') ? <a className="btn" href="#meeting-participants">Review speakers</a> : <button className="btn" disabled={disabled || !loaded || done || running || process.loading || retry.loading || transcript?.status === 'deleted'} onClick={() => process.mutate()}>
        {process.loading ? 'Queuing...' : done ? 'Processing complete' : running ? 'Processing...' : resumable ? 'Resume unfinished' : 'Process meeting'}
      </button>}
      <ManualMeetingAnalysis meetingId={meetingId} disabled={disabled || !loaded || running || process.loading || retry.loading || transcript?.status !== 'ready'} onChanged={onChanged} /></div>
    </div>
    <details className="meeting-processing-details"><summary>Processing details</summary><div className="processing-stages">
      <div><h4><a className="text-link" href="#meeting-transcript">Transcript</a></h4><p>{transcript ? LABELS[transcript.status] : 'Loading...'}</p></div>
      <div><h4><a className="text-link" href="#meeting-participants">Speaker identification</a></h4><p>{speakers ? LABELS[speakers.status] : 'Loading...'}</p>
        {speakers?.status === 'legacy' && <p className="text-muted-sm">This meeting has not had speaker identification. Use Identify speakers in Transcript to request a review.</p>}
        {speakers && speakers.progress.total_units !== null && <p className="text-muted-sm">{speakers.progress.processed_units} of {speakers.progress.total_units} statements reviewed · {speakers.progress.saved_count} identified</p>}
        {speakers?.error_type && <><p role="alert">Speaker identification did not produce a valid saved result. Review transcript assignments or request identification again. Uncertain statements remain unassigned.</p><details><summary>Technical details</summary>{speakers.error_type}</details></>}
        {speakers?.progress.next_attempt_at && speakers.status === 'pending' && <p className="text-muted-sm">Next eligible attempt: {new Date(speakers.progress.next_attempt_at).toLocaleString()}</p>}
        <a className="text-link" href="#meeting-participants">Manage speaker assignments</a>
      </div>
      {([['Memories', 'memories', memories], ['Profiles', 'profiles', personas]] as const).map(([label, stage, result]) => <div key={stage}>
        <h4><a className="text-link" href={stage === 'memories' ? '#meeting-memories' : '#meeting-profiles'}>{label}</a></h4>
        <p>{result ? LABELS[result.status] : 'Loading...'}</p>
        {result && <MeetingGenerationProgress result={result} output={stage} />}
        {result?.status === 'failed' && <button className="btn btn-sm" disabled={disabled || !loaded || retry.loading || process.loading || speakers?.status === 'running' || transcript?.status === 'capturing'} onClick={() => retry.mutate(stage)}>Retry {label.toLowerCase()}</button>}
      </div>)}
    </div>
    <p className="text-muted-sm">Memories and profiles run independently after transcript capture. Completed outputs are kept.</p>
    <p className="text-muted-sm">Profiles use your separate persona job. <Link className="text-link" to="/jobs/new?graph=persona">Create persona job</Link> or <Link className="text-link" to="/jobs">manage existing jobs</Link>.</p></details>
    {notice && <p role="status" style={{ marginTop: 12 }}>{notice}</p>}
  </section>;
}
