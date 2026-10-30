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

export function MeetingProfiles({ meetingId, refreshVersion, onState, active = true, onChanged }: { meetingId: string; active?: boolean; onChanged?: () => void; refreshVersion?: number; onState?: (state: Personas) => void }) {
  const read = useCallback(() => api.meetings.profiles(meetingId), [meetingId]);
  const { data, loading, error, refresh } = useApiRead(read, { enabled: active });
  useRefreshSignal(refreshVersion, refresh);
  useEffect(() => { if (data) onState?.(data); }, [data, onState]);
  const retry = useApiMutation({
    mutationFn: () => api.meetings.retryProfiles(meetingId),
    onSuccess: () => { refresh(); onChanged?.(); },
    onError: () => undefined,
  });
  usePolling(() => refresh({ showLoading: false }), {
    enabled: active && !retry.loading && (data?.status === 'pending' || data?.status === 'running' || data?.reason === 'transcript_pending' || data?.reason === 'memories_pending'),
  });

  if (!active) return null;
  return (
    <section id="meeting-profiles" className="card" aria-label="Meeting participant profiles">
      <div className="participants-header">
        <h3 className="section-title">Linked profiles</h3>
        <a className="btn" href="#meeting-participants">Manage participants</a>
      </div>
      {!data && loading && <p className="text-muted-sm">Loading participant profiles...</p>}
      {error && <div role="alert"><p>Could not load participant profiles. Try again.</p><button className="btn" onClick={() => refresh()} disabled={loading}>Retry</button></div>}
      {data && <>
        {data.items.length > 0 ? <div className="meeting-linked-profiles" role="region" aria-label="Linked profiles list" tabIndex={0}>
          <table className="table" aria-label="Linked participant profiles">
            <thead><tr><th>Name</th><th>Email</th><th className="text-right">Actions</th></tr></thead>
            <tbody>{data.items.map(profile => <tr key={profile.id}>
              <td>{profile.display_name}</td><td className="text-muted-sm">{profile.email || '—'}</td>
              <td className="text-right"><Link className="btn btn-sm" aria-label={`View ${profile.display_name}'s profile`} to={`/profiles/${profile.id}`}>View profile</Link></td>
            </tr>)}</tbody>
          </table>
        </div> : <p className="text-muted-sm">No profiles are linked to this meeting yet. Use Manage participants to connect an existing profile.</p>}
        <h4>Profile analysis</h4>
        <MeetingGenerationState result={data} output="profiles" blockedMessage={blockedMessage(data.reason)}
          retrying={retry.loading} retryFailed={Boolean(retry.error)} onRetry={() => retry.mutate()} />
        {data.status === 'done' && <p className="text-muted-sm">{data.reason || 'Profile analysis is complete. Linked profiles reflect their current saved information.'}</p>}
      </>}
    </section>
  );
}
