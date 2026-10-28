import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { MeetingTranscript as Transcript, TranscriptSegment } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePolling } from '../hooks/usePolling';

const STATUS_MESSAGES: Record<Exclude<Transcript['status'], 'ready'>, string> = {
  not_imported: 'Transcript not imported. Existing meetings are not imported retroactively.',
  pending: 'Transcript capture is pending.',
  capturing: 'Importing transcript...',
  unsupported: 'This meeting connection does not support transcripts.',
  unavailable: 'The meeting provider has no transcript available.',
  failed: 'Transcript import failed.',
  deleted: 'Saved transcript deleted. It will not be imported again automatically.',
};

function speakerName(speaker: TranscriptSegment['speaker']): string {
  return speaker.name || (speaker.diarization_label ? `${speaker.diarization_label} (unidentified)` : 'Unknown speaker');
}

function transcriptTime(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function MeetingTranscript({ meetingId }: { meetingId: string }) {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [failedOffset, setFailedOffset] = useState(0);
  const requestId = useRef(0);

  const load = useCallback(async (offset = 0) => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const result = await api.meetings.transcript(meetingId, { limit: 100, offset });
      if (currentRequest === requestId.current) {
        setTranscript(result);
        setSegments(previous => offset === 0 ? result.items : [...previous, ...result.items]);
      }
    } catch (err) {
      if (currentRequest === requestId.current) {
        setError(err instanceof Error ? err.message : String(err));
        setFailedOffset(offset);
      }
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }, [meetingId]);

  useEffect(() => {
    load();
    return () => { requestId.current += 1; };
  }, [load]);
  const deletion = useApiMutation({
    mutationFn: () => api.meetings.deleteTranscript(meetingId),
    onSuccess: () => {
      requestId.current += 1;
      setTranscript(previous => previous && { ...previous, status: 'deleted', items: [], total: 0, captured_at: null, error_type: null });
      setSegments([]);
      setError(null);
      setLoading(false);
    },
  });
  const retryCapture = useApiMutation({
    mutationFn: () => api.meetings.retryTranscript(meetingId),
    onSuccess: () => load(),
  });
  usePolling(() => load(), {
    enabled: !deletion.loading && !retryCapture.loading && (transcript?.status === 'pending' || transcript?.status === 'capturing'),
  });

  const deleteTranscript = () => {
    if (!confirm('Delete this saved transcript? It will not be imported again automatically.')) return;
    requestId.current += 1;
    setLoading(false);
    deletion.mutate();
  };
  const canDelete = transcript && transcript.status !== 'not_imported' && transcript.status !== 'deleted';
  const canRetry = transcript && ['failed', 'unsupported', 'unavailable'].includes(transcript.status);

  return (
    <section id="meeting-transcript" className="card" aria-label="Meeting transcript">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h3 className="section-title" style={{ margin: 0 }}>Transcript</h3>
        {canDelete && (
          <button className="btn btn-sm btn-danger" onClick={deleteTranscript} disabled={deletion.loading || retryCapture.loading}>
            {deletion.loading ? 'Deleting...' : 'Delete saved transcript'}
          </button>
        )}
      </div>
      {!transcript && loading && <p className="text-muted-sm">Loading transcript...</p>}
      {error && (
        <div role="alert">
          <p>Could not load transcript: {error}</p>
          <button className="btn" onClick={() => load(failedOffset)} disabled={loading || deletion.loading || retryCapture.loading}>Retry</button>
        </div>
      )}
      {transcript && transcript.status !== 'ready' && (
        <p className="text-muted-sm">
          {STATUS_MESSAGES[transcript.status]}
          {transcript.error_type && <> Error: {transcript.error_type}.</>}
        </p>
      )}
      {canRetry && (
        <div>
          <button className="btn" onClick={() => retryCapture.mutate()} disabled={retryCapture.loading || deletion.loading}>
            {retryCapture.loading ? 'Queuing...' : 'Retry capture'}
          </button>
          <p className="text-muted-sm">Queues transcript capture for the next meeting import run.</p>
        </div>
      )}
      {transcript?.status === 'ready' && (
        <>
          {segments.length === 0 && <p className="text-muted-sm">The saved transcript is empty.</p>}
          {segments.map(segment => (
            <article key={segment.id} id={`transcript-${segment.id}`} style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <strong>{speakerName(segment.speaker)}</strong>
                {segment.start_time && (
                  <span className="text-muted-sm">
                    <time dateTime={segment.start_time}>{transcriptTime(segment.start_time)}</time>
                    {segment.end_time && <> – <time dateTime={segment.end_time}>{transcriptTime(segment.end_time)}</time></>}
                  </span>
                )}
                {segment.speaker.attribution && <span className="text-muted-sm">{segment.speaker.attribution}</span>}
              </div>
              <p style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{segment.text}</p>
            </article>
          ))}
          {segments.length < transcript.total && (
            <button className="btn" onClick={() => load(segments.length)} disabled={loading || deletion.loading}>
              {loading ? 'Loading...' : 'Load more transcript'}
            </button>
          )}
        </>
      )}
    </section>
  );
}
