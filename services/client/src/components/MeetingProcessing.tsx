import { useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { MeetingGeneration, MeetingProcessingState } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { ManualMeetingAnalysis } from './ManualMeetingAnalysis';
import { MeetingGenerationProgress } from './MeetingGenerationProgress';
import { MEMORY_RESTART_HELP } from '../utils/memoryRetry';

const LABELS: Record<string, string> = { not_imported: 'Not queued', pending: 'Queued', running: 'Running', capturing: 'Running', ready: 'Complete', done: 'Complete', blocked: 'Waiting for transcript', failed: 'Needs attention', unavailable: 'Unavailable', unsupported: 'Unsupported', deleted: 'Deleted' };

export function MeetingProcessing({ meetingId, transcript, memories, personas, onChanged, disabled = false }: {
  meetingId: string; transcript: MeetingProcessingState['transcript'] | null; memories: MeetingGeneration | null; personas: MeetingGeneration | null;
  onChanged: () => void; disabled?: boolean;
}) {
  const [notice, setNotice] = useState<string | null>(null);
  const process = useApiMutation({ mutationFn: () => api.meetings.process(meetingId),
    onSuccess: result => { setNotice(result.status === 'done' ? 'Both workflows are complete.' : 'Missing work is queued for your meeting and persona jobs. Completed outputs are preserved.'); onChanged(); },
    onError: () => setNotice('Could not queue processing. Try again.'),
  });
  const retry = useApiMutation({ mutationFn: async (stage: 'memories' | 'profiles') => {
    await (stage === 'memories' ? api.meetings.retryMemories(meetingId) : api.meetings.retryProfiles(meetingId));
    return stage;
  }, onSuccess: stage => {
    setNotice(stage === 'memories' ? `Memory retry queued. ${MEMORY_RESTART_HELP} Published memories are kept.` : 'Retry queued. Completed work is preserved.');
    onChanged();
  }, onError: () => setNotice('Could not queue this retry. Try again.') });
  const loaded = Boolean(transcript && memories && personas);
  const done = transcript?.status === 'ready' && memories?.status === 'done' && personas?.status === 'done';
  const running = transcript?.status === 'capturing' || memories?.status === 'running' || personas?.status === 'running';
  const resumable = memories?.progress?.processed_units || personas?.progress?.processed_units || transcript?.status === 'pending' || memories?.status === 'pending' || personas?.status === 'pending';
  return <section className="meeting-processing" aria-label="Meeting processing">
    <div className="meeting-processing-summary">
      <div className="flex-wrap meeting-stage-badges">{[['Transcript', '#meeting-transcript', transcript], ['Memories', '#meeting-memories', memories], ['Profiles', '#meeting-profiles', personas]].map(([label, href, result]) => {
        const stage = result as { status: string; progress?: MeetingGeneration['progress'] } | null | undefined;
        const statusLabel = stage?.status === 'pending' && (stage.progress?.processed_units ?? 0) > 0 ? 'Progress saved' : stage ? LABELS[stage.status] || stage.status : 'Loading...';
        return <a className={`tag text-link${stage?.status === 'failed' ? ' tag-danger' : ''}`} key={label as string} href={href as string}>{label as string}: {statusLabel}</a>;
      })}</div>
      <div className="flex-wrap"><button className="btn" disabled={disabled || !loaded || done || running || process.loading || retry.loading || transcript?.status === 'deleted'} onClick={() => process.mutate()}>
        {process.loading ? 'Queuing...' : done ? 'Processing complete' : running ? 'Processing...' : resumable ? 'Continue processing' : 'Process meeting'}
      </button>
      <ManualMeetingAnalysis meetingId={meetingId} disabled={disabled || !loaded || running || process.loading || retry.loading || transcript?.status !== 'ready'} onChanged={onChanged} /></div>
    </div>
    <details className="meeting-processing-details"><summary>Processing details</summary><div className="processing-stages">
      <div><h4><a className="text-link" href="#meeting-transcript">Transcript</a></h4><p>{transcript ? LABELS[transcript.status] : 'Loading...'}</p></div>
      {([['Memories', 'memories', memories], ['Profiles', 'profiles', personas]] as const).map(([label, stage, result]) => <div key={stage}>
        <h4><a className="text-link" href={stage === 'memories' ? '#meeting-memories' : '#meeting-profiles'}>{label}</a></h4>
        <p>{result ? LABELS[result.status] : 'Loading...'}</p>
        {result && <MeetingGenerationProgress result={result} output={stage} />}
        {stage === 'memories' && result?.status === 'failed' && <p className="text-muted-sm">{MEMORY_RESTART_HELP}</p>}
        {result?.status === 'failed' && <button className="btn btn-sm" disabled={disabled || !loaded || retry.loading || process.loading || transcript?.status === 'capturing'} onClick={() => retry.mutate(stage)}>Retry {label.toLowerCase()}</button>}
      </div>)}
    </div>
    <p className="text-muted-sm">Memories and profiles run independently after transcript capture. Completed outputs are kept.</p>
    <p className="text-muted-sm">Profiles use your separate persona job. <Link className="text-link" to="/jobs/new?graph=persona">Create persona job</Link> or <Link className="text-link" to="/jobs">manage existing jobs</Link>.</p></details>
    {notice && <p role="status" style={{ marginTop: 12 }}>{notice}</p>}
  </section>;
}
