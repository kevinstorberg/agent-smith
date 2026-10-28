import { useCallback } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { MeetingMemory } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { useApiRead } from '../hooks/useApiRead';
import { usePolling } from '../hooks/usePolling';

const KIND_LABELS: Record<MeetingMemory['kind'], string> = {
  fact: 'Fact', decision: 'Decision', commitment: 'Commitment', constraint: 'Constraint',
  preference: 'Preference', lesson: 'Lesson', question: 'Open question',
};

const BLOCKED_MESSAGES: Record<string, string> = {
  transcript_pending: 'Memories need a complete saved transcript. Transcript capture is still pending.',
  transcript_deleted: 'Memories cannot be generated because the saved transcript was deleted.',
  transcript_unsupported: 'This meeting connection does not provide a transcript for memory generation.',
  transcript_unavailable: 'The provider has no transcript available for memory generation.',
  transcript_failed: 'Transcript capture failed. Retry transcript capture before generating memories.',
};

export function MeetingMemories({ meetingId }: { meetingId: string }) {
  const read = useCallback(() => api.meetings.memories(meetingId), [meetingId]);
  const { data: memories, loading, error, refresh: load } = useApiRead(read);

  const retry = useApiMutation({
    mutationFn: () => api.meetings.retryMemories(meetingId),
    onSuccess: () => load(),
    onError: () => undefined,
  });
  usePolling(() => load({ showLoading: false }), {
    enabled: !retry.loading && (memories?.status === 'pending' || memories?.status === 'running' || memories?.reason === 'transcript_pending'),
  });

  return (
    <section className="card" aria-label="Meeting memories">
      <h3 className="section-title">Generated memories</h3>
      {!memories && loading && <p className="text-muted-sm">Loading meeting memories...</p>}
      {error && (
        <div role="alert">
          <p>Could not load meeting memories. Try again.</p>
          <button className="btn" onClick={() => load()} disabled={loading || retry.loading}>Retry</button>
        </div>
      )}
      {memories?.status === 'not_imported' && <p className="text-muted-sm">Memory generation is not enabled for this older meeting. Existing meetings are not processed retroactively.</p>}
      {memories?.status === 'pending' && <p className="text-muted-sm">Memory generation is queued for the next meeting import run.</p>}
      {memories?.status === 'running' && <p className="text-muted-sm">Generating meeting memories...</p>}
      {memories?.status === 'blocked' && (
        <p className="text-muted-sm">{BLOCKED_MESSAGES[memories.reason ?? ''] || 'Memories need a complete saved transcript. Check the transcript status.'}</p>
      )}
      {memories?.status === 'failed' && (
        <div>
          <p className="text-muted-sm">Memory generation failed.</p>
          <button className="btn" onClick={() => retry.mutate()} disabled={retry.loading}>
            {retry.loading ? 'Queuing...' : 'Retry generation'}
          </button>
          <p className="text-muted-sm">Queues another attempt for the next meeting import run.</p>
          {retry.error && <p role="alert">Could not queue another attempt. Try again.</p>}
        </div>
      )}
      {memories?.status === 'done' && (
        <>
          {memories.items.length === 0 ? (
            <p className="text-muted-sm">{memories.reason || 'No new durable memories were found in this meeting.'}</p>
          ) : memories.items.map(memory => (
            <article key={memory.id} style={{ borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 12 }}>
              <span className="tag">{KIND_LABELS[memory.kind]}</span>
              <p style={{ whiteSpace: 'pre-wrap' }}>{memory.content}</p>
              <details>
                <summary>Source evidence</summary>
                {memory.evidence.map((evidence, index) => (
                  <blockquote key={`${evidence.segment_id}-${index}`}>
                    <p style={{ whiteSpace: 'pre-wrap' }}>{evidence.quote}</p>
                    <cite className="text-muted-sm">Transcript {evidence.segment_id}</cite>
                  </blockquote>
                ))}
                <a href="#meeting-transcript">View transcript</a>
              </details>
            </article>
          ))}
          {memories.items.length > 0 && <p><Link to="/memory">Manage saved memories</Link></p>}
        </>
      )}
    </section>
  );
}
