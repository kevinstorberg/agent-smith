import type { MeetingGeneration } from '../api';
import { DateCell } from './table';

interface Props {
  result: Pick<MeetingGeneration, 'status' | 'progress' | 'error_type'>;
  output: 'memories' | 'profiles';
}

function failureSummary(errorType: string, status: MeetingGeneration['status']): string {
  if (/inputchanged|superseded/i.test(errorType)) return 'Meeting context changed. Review the meeting and confirm a fresh analysis request. Existing saved outputs are kept.';
  if (/revisionconflict/i.test(errorType)) return 'The profile changed during analysis. Unfinished work must use the updated profile. Existing saved outputs are kept.';
  const reason = /timeout|timedout|deadline|budgetexpired/i.test(errorType) ? 'The last attempt timed out.' : 'The last attempt could not finish.';
  return `${reason} Saved progress is kept.${status === 'failed' ? ' Retry this stage to continue.' : ''}`;
}

export function MeetingGenerationProgress({ result, output }: Props) {
  const progress = result.progress;
  const failedAttempt = result.status !== 'done' && result.error_type;
  if (!progress && !failedAttempt) return null;
  return <div className="processing-progress">
    {progress && <>
      {progress.total_units !== null && progress.total_units > 0 && <>
        <progress aria-label={`${output === 'memories' ? 'Memory' : 'Profile'} analysis progress`} max={progress.total_units} value={Math.min(progress.processed_units, progress.total_units)} />
        <p className="text-muted-sm">{progress.processed_units} of {progress.total_units} transcript sections analyzed</p>
      </>}
      <p className="text-muted-sm">{progress.staged_count} candidates saved · {progress.saved_count} {output === 'memories' ? 'memories published' : 'profiles updated'}</p>
      {result.status === 'pending' && progress.processed_units > 0 && <p className="text-muted-sm">Saved progress will resume; completed sections will not be repeated.</p>}
      {result.status === 'pending' && progress.next_attempt_at && <p className="text-muted-sm">Next eligible attempt: <DateCell date={progress.next_attempt_at} format="long" /></p>}
    </>}
    {failedAttempt && <p className="text-muted-sm" role="status">{failureSummary(failedAttempt, result.status)}</p>}
  </div>;
}
