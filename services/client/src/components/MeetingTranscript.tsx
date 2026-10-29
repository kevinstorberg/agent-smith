import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { MeetingTranscript as Transcript, TranscriptSegment } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePolling } from '../hooks/usePolling';
import { useRefreshSignal } from '../hooks/useRefreshSignal';

const STATUS_MESSAGES: Record<Exclude<Transcript['status'], 'ready'>, string> = {
  not_imported: 'Transcript not imported yet. Use Process meeting above to queue capture.',
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

export function MeetingTranscript({ meetingId, refreshVersion, onState }: { meetingId: string; refreshVersion?: number; onState?: (state: Transcript) => void }) {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [failedOffset, setFailedOffset] = useState(0);
  const [failedPreserve, setFailedPreserve] = useState(false);
  const requestId = useRef(0);
  const loadedCount = useRef(0);

  const load = useCallback(async (offset = 0, preserveLoaded = false) => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const collected: TranscriptSegment[] = [];
      const wanted = preserveLoaded ? Math.max(100, loadedCount.current) : 100;
      let result: Transcript;
      let pageOffset = offset;
      do {
        result = await api.meetings.transcript(meetingId, { limit: 100, offset: pageOffset });
        if (currentRequest !== requestId.current) return;
        collected.push(...result.items);
        pageOffset += result.items.length;
      } while (preserveLoaded && result.items.length > 0 && collected.length < wanted && pageOffset < result.total);
      if (currentRequest === requestId.current) {
        setTranscript(result);
        loadedCount.current = offset === 0 ? collected.length : loadedCount.current + collected.length;
        setSegments(previous => offset === 0 ? collected : [...previous, ...collected]);
      }
    } catch (err) {
      if (currentRequest === requestId.current) {
        setError(err instanceof Error ? err.message : String(err));
        setFailedOffset(offset);
        setFailedPreserve(preserveLoaded);
      }
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }, [meetingId]);
  const refreshLoaded = useCallback(() => load(0, true), [load]);
  useRefreshSignal(refreshVersion, refreshLoaded);
  useEffect(() => { if (transcript) onState?.(transcript); }, [transcript, onState]);

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
          <button className="btn" onClick={() => load(failedOffset, failedPreserve)} disabled={loading || deletion.loading || retryCapture.loading}>Retry</button>
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
          <p style={{ marginBottom: 12 }}><a className="text-link" href="#meeting-participants">Identify speakers</a></p>
          {segments.length === 0 && <p className="text-muted-sm">The saved transcript is empty.</p>}
          {segments.map(segment => (
            <article key={segment.id} id={`transcript-${segment.id}`} style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <strong>{segment.effective_speaker?.profile_id
                  ? <Link className="text-link" to={`/profiles/${segment.effective_speaker.profile_id}`}>{segment.effective_speaker.display_name}</Link>
                  : segment.effective_speaker?.display_name || speakerName(segment.speaker)}</strong>
                {segment.effective_speaker?.source === 'manual_assignment' && <span className="tag tag-sm">Assigned by you</span>}
                {segment.start_time && (
                  <span className="text-muted-sm">
                    <time dateTime={segment.start_time}>{transcriptTime(segment.start_time)}</time>
                    {segment.end_time && <> – <time dateTime={segment.end_time}>{transcriptTime(segment.end_time)}</time></>}
                  </span>
                )}
                {segment.speaker.attribution && <span className="text-muted-sm">{segment.speaker.attribution}</span>}
                {segment.effective_speaker && <span className="text-muted-sm">Original: {[speakerName(segment.speaker), segment.speaker.source].filter(Boolean).join(' · ')}</span>}
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
