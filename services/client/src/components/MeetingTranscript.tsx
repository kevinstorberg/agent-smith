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

export function MeetingTranscript({ meetingId, refreshVersion, onState, onAssign, assignmentDisabled = false, active = true, targetSegment = null, onChanged, onShowBeginning }: {
  meetingId: string; refreshVersion?: number; onState?: (state: Transcript) => void; onAssign?: (statement: TranscriptSegment) => void;
  assignmentDisabled?: boolean; active?: boolean; targetSegment?: number | null; onChanged?: () => void; onShowBeginning?: () => void;
}) {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [failedOffset, setFailedOffset] = useState(0);
  const [failedPreserve, setFailedPreserve] = useState(false);
  const requestId = useRef(0);
  const loadedCount = useRef(0);
  const baseOffset = useRef(0);
  const activeRef = useRef(active);
  const mounted = useRef(false);
  const [windowStart, setWindowStart] = useState(0);
  const [failedReplace, setFailedReplace] = useState(true);
  const focusedTarget = useRef<number | null>(null);
  useEffect(() => { activeRef.current = active; }, [active]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const load = useCallback(async (offset = baseOffset.current, preserveLoaded = false, replace = true) => {
    if (!activeRef.current || !mounted.current) return;
    const currentRequest = ++requestId.current;
    setLoading(true); setError(null);
    try {
      const collected: TranscriptSegment[] = [];
      const wanted = preserveLoaded ? loadedCount.current || 100 : 100;
      let result: Transcript;
      let pageOffset = offset;
      do {
        result = await api.meetings.transcript(meetingId, { limit: 100, offset: pageOffset });
        if (currentRequest !== requestId.current || !mounted.current || !activeRef.current) return;
        collected.push(...result.items);
        pageOffset += result.items.length;
      } while (preserveLoaded && result.items.length > 0 && collected.length < wanted && pageOffset < result.total);
      setTranscript(result);
      if (replace) { baseOffset.current = offset; loadedCount.current = collected.length; setWindowStart(offset); setSegments(collected); }
      else { loadedCount.current += collected.length; setSegments(previous => [...previous, ...collected]); }
    } catch (err) {
      if (currentRequest === requestId.current && mounted.current) {
        setError(err instanceof Error ? err.message : String(err)); setFailedOffset(offset); setFailedPreserve(preserveLoaded); setFailedReplace(replace);
      }
    } finally {
      if (currentRequest === requestId.current && mounted.current) setLoading(false);
    }
  }, [meetingId]);
  const refreshLoaded = useCallback(() => load(baseOffset.current, true), [load]);
  useRefreshSignal(refreshVersion, refreshLoaded);
  useEffect(() => { if (transcript) onState?.(transcript); }, [transcript, onState]);
  useEffect(() => {
    if (active) {
      const outside = targetSegment !== null && (targetSegment < baseOffset.current || targetSegment >= baseOffset.current + loadedCount.current);
      load(outside ? Math.floor(targetSegment / 100) * 100 : baseOffset.current, !outside && loadedCount.current > 0);
    }
    return () => { requestId.current += 1; };
  }, [active, load, targetSegment]);
  useEffect(() => {
    if (targetSegment === null) { focusedTarget.current = null; return; }
    if (!active || loading || focusedTarget.current === targetSegment) return;
    const target = document.getElementById(`transcript-segment-${targetSegment}`);
    if (target) { target.scrollIntoView({ block: 'start' }); target.setAttribute('tabindex', '-1'); target.focus({ preventScroll: true }); focusedTarget.current = targetSegment; }
  }, [active, targetSegment, loading, segments]);
  const deletion = useApiMutation({
    mutationFn: () => api.meetings.deleteTranscript(meetingId),
    onSuccess: () => {
      if (!mounted.current) return;
      requestId.current += 1;
      setTranscript(previous => previous && { ...previous, status: 'deleted', items: [], total: 0, captured_at: null, error_type: null });
      setSegments([]);
      setError(null);
      setLoading(false); onChanged?.();
    },
  });
  const retryCapture = useApiMutation({
    mutationFn: () => api.meetings.retryTranscript(meetingId),
    onSuccess: () => { if (mounted.current) { load(); onChanged?.(); } },
  });
  usePolling(() => load(), {
    enabled: active && !deletion.loading && !retryCapture.loading && (transcript?.status === 'pending' || transcript?.status === 'capturing'),
  });

  const deleteTranscript = () => {
    if (!confirm('Delete this saved transcript? It will not be imported again automatically.')) return;
    requestId.current += 1;
    setLoading(false);
    deletion.mutate();
  };
  const canDelete = transcript && transcript.status !== 'not_imported' && transcript.status !== 'deleted';
  const canRetry = transcript && ['failed', 'unsupported', 'unavailable'].includes(transcript.status);

  if (!active) return null;
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
          <button className="btn" onClick={() => load(failedOffset, failedPreserve, failedReplace)} disabled={loading || deletion.loading || retryCapture.loading}>Retry</button>
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
          {windowStart > 0 && <div className="flex-wrap">{segments.length > 0 && <p className="text-muted-sm">Showing statements {windowStart + 1}–{windowStart + segments.length} of {transcript.total}</p>}<button className="btn btn-sm" onClick={() => { baseOffset.current = 0; loadedCount.current = 0; onShowBeginning?.(); if (!onShowBeginning || targetSegment === null) load(0); }}>Show beginning</button></div>}
          {targetSegment !== null && !loading && !error && !segments.some(segment => segment.id === `segment-${targetSegment}`) && <p role="status">This statement is not available in the saved transcript.</p>}
          {transcript.total === 0 && <p className="text-muted-sm">The saved transcript is empty.</p>}
          {segments.map(segment => (
            <article key={segment.id} id={`transcript-${segment.id}`} style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <strong>{segment.effective_speaker?.profile_id
                  ? <Link className="text-link" to={`/profiles/${segment.effective_speaker.profile_id}`}>{segment.effective_speaker.display_name}</Link>
                  : segment.effective_speaker?.display_name || speakerName(segment.speaker)}</strong>
                {segment.effective_speaker?.source === 'manual_assignment' && <span className="tag tag-sm">Assigned by you</span>}
                {segment.effective_speaker?.source === 'automatic_statement' && <span className="tag tag-sm">Identified from context</span>}
                {onAssign && <button className="btn btn-sm" disabled={assignmentDisabled} onClick={() => onAssign(segment)}>Assign this statement</button>}
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
          {windowStart + segments.length < transcript.total && (
            <button className="btn" onClick={() => load(windowStart + segments.length, false, false)} disabled={loading || deletion.loading}>
              {loading ? 'Loading...' : 'Load more transcript'}
            </button>
          )}
        </>
      )}
    </section>
  );
}
