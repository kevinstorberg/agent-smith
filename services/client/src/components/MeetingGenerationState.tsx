import type { MeetingGeneration } from '../api';

interface Props {
  result: MeetingGeneration;
  output: 'memories' | 'profiles';
  blockedMessage: string;
  retrying: boolean;
  retryFailed: boolean;
  onRetry: () => void;
}

export function MeetingGenerationState({ result, output, blockedMessage, retrying, retryFailed, onRetry }: Props) {
  const subject = output === 'memories' ? 'Memory generation' : 'Profile generation';
  return (
    <>
      {result.status === 'not_imported' && <p className="text-muted-sm">{subject} has not started. Use Process meeting in Participants to queue this meeting.</p>}
      {result.status === 'pending' && <p className="text-muted-sm">{subject} is queued for the next meeting import run.</p>}
      {result.status === 'running' && <p className="text-muted-sm">{output === 'memories' ? 'Generating meeting memories...' : 'Generating participant profiles...'}</p>}
      {result.status === 'blocked' && <p className="text-muted-sm">{blockedMessage}</p>}
      {result.status === 'failed' && (
        <div>
          <p className="text-muted-sm">{subject} failed.</p>
          <button className="btn" onClick={onRetry} disabled={retrying}>{retrying ? 'Queuing...' : 'Retry generation'}</button>
          <p className="text-muted-sm">Queues another attempt for the next meeting import run.</p>
          {retryFailed && <p role="alert">Could not queue another attempt. Try again.</p>}
        </div>
      )}
    </>
  );
}
