import { useCallback, useEffect } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePolling } from '../hooks/usePolling';
import { MeetingGenerationState } from './MeetingGenerationState';
import type { MeetingProfiles as Personas } from '../api';
import { useRefreshSignal } from '../hooks/useRefreshSignal';

function blockedMessage(reason: string | null): string {
  if (reason === 'transcript_deleted') return 'Profiles cannot be generated because the saved transcript was deleted.';
  return 'Personas need a complete saved transcript. Memory generation runs independently.';
}

export function MeetingProfiles({ meetingId, refreshVersion, onState }: { meetingId: string; refreshVersion?: number; onState?: (state: Personas) => void }) {
  const read = useCallback(() => api.meetings.profiles(meetingId), [meetingId]);
  const { data, loading, error, refresh } = useApiRead(read);
  useRefreshSignal(refreshVersion, refresh);
  useEffect(() => { if (data) onState?.(data); }, [data, onState]);
  const retry = useApiMutation({
    mutationFn: () => api.meetings.retryProfiles(meetingId),
    onSuccess: () => refresh(),
    onError: () => undefined,
  });
  usePolling(() => refresh({ showLoading: false }), {
    enabled: !retry.loading && (data?.status === 'pending' || data?.status === 'running' || data?.reason === 'transcript_pending' || data?.reason === 'memories_pending'),
  });

  return (
    <section id="meeting-profiles" className="card" aria-label="Meeting participant profiles">
      <h3 className="section-title">Personas</h3>
      {!data && loading && <p className="text-muted-sm">Loading participant profiles...</p>}
      {error && <div role="alert"><p>Could not load participant profiles. Try again.</p><button className="btn" onClick={() => refresh()} disabled={loading}>Retry</button></div>}
      {data && <MeetingGenerationState result={data} output="profiles" blockedMessage={blockedMessage(data.reason)}
        retrying={retry.loading} retryFailed={Boolean(retry.error)} onRetry={() => retry.mutate()} />}
      {data?.status === 'done' && (data.items.length === 0 ? (
        <p className="text-muted-sm">{data.reason || 'No participant profiles were generated for this meeting.'}</p>
      ) : (
        <ul style={{ listStyle: 'none' }}>
          {data.items.map(profile => <li key={profile.id} style={{ marginBottom: 8 }}>
            <Link to={`/profiles/${profile.id}`}>{profile.display_name}</Link>
            {profile.email && <span className="text-muted-sm"> · {profile.email}</span>}
          </li>)}
        </ul>
      ))}
    </section>
  );
}
