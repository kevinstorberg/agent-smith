import { useCallback, useEffect } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePolling } from '../hooks/usePolling';
import { MeetingGenerationState } from './MeetingGenerationState';
import type { MeetingProfiles as Personas } from '../api';
import { useRefreshSignal } from '../hooks/useRefreshSignal';
import { useLocalTableSort } from '../hooks/useLocalTableSort';
import { SortableHeader } from './table/SortableHeader';
import { ScrollableTable } from './ScrollableTable';
import './meetingProfilesSorting.css';

type LinkedProfile = Personas['items'][number];
const PROFILE_COLUMNS = {
  name: {
    ascending: 'name_asc',
    descending: 'name_desc',
    select: (profile: LinkedProfile) => profile.display_name,
  },
  email: {
    ascending: 'email_asc',
    descending: 'email_desc',
    select: (profile: LinkedProfile) => profile.email || null,
  },
} as const;
const profileId = (profile: LinkedProfile) => profile.id;
const EMPTY_PROFILES: LinkedProfile[] = [];

interface MeetingProfilesProps {
  meetingId: string;
  active?: boolean;
  onChanged?: () => void;
  refreshVersion?: number;
  onState?: (state: Personas) => void;
}

export function MeetingProfiles(props: MeetingProfilesProps) {
  return <MeetingProfileContent key={props.meetingId} {...props} />;
}

function blockedMessage(reason: string | null): string {
  if (reason === 'transcript_deleted')
    return 'Profiles cannot be generated because the saved transcript was deleted.';
  return 'Personas need a complete saved transcript. Memory generation runs independently.';
}

function MeetingProfileContent({
  meetingId,
  refreshVersion,
  onState,
  active = true,
  onChanged,
}: MeetingProfilesProps) {
  const read = useCallback(() => api.meetings.profiles(meetingId), [meetingId]);
  const { data, loading, error, refresh } = useApiRead(read, {
    enabled: active,
  });
  useRefreshSignal(refreshVersion, refresh);
  const profiles = useLocalTableSort(
    data?.items ?? EMPTY_PROFILES,
    PROFILE_COLUMNS,
    profileId,
  );
  useEffect(() => {
    if (data) onState?.(data);
  }, [data, onState]);
  const retry = useApiMutation({
    mutationFn: () => api.meetings.retryProfiles(meetingId),
    onSuccess: () => {
      refresh();
      onChanged?.();
    },
    onError: () => undefined,
  });
  usePolling(() => refresh({ showLoading: false }), {
    enabled:
      active &&
      !retry.loading &&
      (data?.status === 'pending' ||
        data?.status === 'running' ||
        data?.reason === 'transcript_pending' ||
        data?.reason === 'memories_pending'),
  });

  if (!active) return null;
  return (
    <section
      id="meeting-profiles"
      className="card"
      aria-label="Meeting participant profiles"
    >
      <div className="participants-header">
        <h3 className="section-title">Linked profiles</h3>
        <a className="btn" href="#meeting-participants">
          Manage participants
        </a>
      </div>
      {!data && loading && (
        <p className="text-muted-sm">Loading participant profiles...</p>
      )}
      {error && (
        <div role="alert">
          <p>Could not load participant profiles. Try again.</p>
          <button className="btn" onClick={() => refresh()} disabled={loading}>
            Retry
          </button>
        </div>
      )}
      {data && (
        <>
          <div className="meeting-profile-links">
            <ScrollableTable
              label="Linked profiles list"
              tableLabel="Linked participant profiles"
              className="linked-meeting-profiles-table"
              busy={loading}
              emptyState={
                data.items.length === 0 ? (
                  <p className="text-muted-sm">
                    No profiles are linked to this meeting yet. Use Manage
                    participants to connect an existing profile.
                  </p>
                ) : undefined
              }
            >
              <colgroup>
                <col />
                <col />
                <col className="linked-profile-actions" />
              </colgroup>
              <thead>
                <tr>
                  <SortableHeader
                    sort={profiles.sort}
                    column={PROFILE_COLUMNS.name}
                    onSort={profiles.setSort}
                  >
                    Name
                  </SortableHeader>
                  <SortableHeader
                    sort={profiles.sort}
                    column={PROFILE_COLUMNS.email}
                    onSort={profiles.setSort}
                  >
                    Email
                  </SortableHeader>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {profiles.items.map((profile) => (
                  <tr key={profile.id}>
                    <td>{profile.display_name}</td>
                    <td className="text-muted-sm">{profile.email || '—'}</td>
                    <td className="text-right">
                      <Link
                        className="btn btn-sm"
                        aria-label={`View ${profile.display_name}'s profile`}
                        to={`/profiles/${profile.id}`}
                      >
                        View profile
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </ScrollableTable>
          </div>
          <h4>Profile analysis</h4>
          <MeetingGenerationState
            result={data}
            output="profiles"
            blockedMessage={blockedMessage(data.reason)}
            retrying={retry.loading}
            retryFailed={Boolean(retry.error)}
            onRetry={() => retry.mutate()}
          />
          {data.status === 'done' && (
            <p className="text-muted-sm">
              {data.reason ||
                'Profile analysis is complete. Linked profiles reflect their current saved information.'}
            </p>
          )}
        </>
      )}
    </section>
  );
}
