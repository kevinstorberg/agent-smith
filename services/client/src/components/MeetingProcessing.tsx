import { useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { MeetingGeneration, MeetingMemories, MeetingProfiles, MeetingTranscript } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { ManualMeetingAnalysis } from './ManualMeetingAnalysis';

const LABELS: Record<string, string> = { not_imported: 'Not queued', pending: 'Queued', running: 'Running', capturing: 'Running', ready: 'Complete', done: 'Complete', blocked: 'Waiting for transcript', failed: 'Needs attention', unavailable: 'Unavailable', unsupported: 'Unsupported', deleted: 'Deleted' };

function Progress({ result, output }: { result: MeetingGeneration; output: 'memories' | 'profiles' }) {
  const progress = result.progress;
  if (!progress) return null;
  return <div className="processing-progress">
    {progress.total_units !== null && progress.total_units > 0 && <>
      <progress aria-label={`${output === 'memories' ? 'Memory' : 'Persona'} analysis progress`} max={progress.total_units} value={Math.min(progress.processed_units, progress.total_units)} />
      <p className="text-muted-sm">{progress.processed_units} of {progress.total_units} transcript sections analyzed</p>
    </>}
    <p className="text-muted-sm">{progress.staged_count} candidates saved · {progress.saved_count} {output === 'memories' ? 'memories published' : 'profiles updated'}</p>
    {result.status === 'pending' && progress.processed_units > 0 && <p className="text-muted-sm">Saved progress will resume; completed sections will not be repeated.</p>}
    {progress.next_attempt_at && result.status !== 'done' && <p className="text-muted-sm">Next eligible attempt: {new Date(progress.next_attempt_at).toLocaleString()}</p>}
  </div>;
}

export function MeetingProcessing({ meetingId, transcript, memories, personas, onChanged, disabled = false }: {
  meetingId: string; transcript: MeetingTranscript | null; memories: MeetingMemories | null; personas: MeetingProfiles | null; onChanged: () => void; disabled?: boolean;
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
  const running = transcript?.status === 'capturing' || memories?.status === 'running' || personas?.status === 'running';
  const resumable = memories?.progress?.processed_units || personas?.progress?.processed_units || transcript?.status === 'pending';
  return <section className="card" aria-label="Meeting processing">
    <div className="page-header profiles-header"><h3 className="section-title">Processing</h3>
      <div className="flex-wrap"><button className="btn" disabled={disabled || !loaded || done || running || process.loading || retry.loading || transcript?.status === 'deleted'} onClick={() => process.mutate()}>
        {process.loading ? 'Queuing...' : done ? 'Processing complete' : running ? 'Processing...' : resumable ? 'Resume unfinished' : 'Process meeting'}
      </button>
      <ManualMeetingAnalysis meetingId={meetingId} disabled={disabled || !loaded || running || process.loading || retry.loading || transcript?.status !== 'ready'} onChanged={onChanged} /></div>
    </div>
    <div className="processing-stages">
      <div><h4><a className="text-link" href="#meeting-transcript">Transcript</a></h4><p>{transcript ? LABELS[transcript.status] : 'Loading...'}</p></div>
      {([['Memories', 'memories', memories], ['Personas', 'profiles', personas]] as const).map(([label, stage, result]) => <div key={stage}>
        <h4><a className="text-link" href={stage === 'memories' ? '#meeting-memories' : '#meeting-profiles'}>{label}</a></h4>
        <p>{result ? LABELS[result.status] : 'Loading...'}</p>
        {result && <Progress result={result} output={stage} />}
        {result?.status === 'failed' && <button className="btn btn-sm" disabled={retry.loading || process.loading} onClick={() => retry.mutate(stage)}>Retry {label.toLowerCase()}</button>}
      </div>)}
    </div>
    <p className="text-muted-sm">Memories and personas run independently after transcript capture. Completed outputs are kept.</p>
    <p className="text-muted-sm">Persona enrichment needs a separate persona job. <Link className="text-link" to="/jobs/new?graph=persona">Create persona job</Link> or <Link className="text-link" to="/jobs">manage existing jobs</Link>. It reads saved transcripts and can continue even if memory generation fails.</p>
    {notice && <p role="status" style={{ marginTop: 12 }}>{notice}</p>}
  </section>;
}
