import { useState } from 'react';
import { api } from '../api';
import type { MeetingActionItemProposals as ProposalState } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';
import { ButtonLink } from './ButtonLink';
import { DateCell } from './table';

const LABELS: Record<ProposalState['status'], string> = {
  not_queued: 'Not generated',
  pending: 'Queued',
  running: 'Generating proposals',
  done: 'Complete',
  failed: 'Needs attention',
};

export function MeetingActionItemProposals({
  meetingId,
  revision,
  state,
  onChanged,
  disabled = false,
}: {
  meetingId: string;
  revision: number;
  state: ProposalState | null;
  onChanged: () => void;
  disabled?: boolean;
}) {
  const [notice, setNotice] = useState<string | null>(null);
  const request = useApiMutation({
    mutationFn: () =>
      api.meetings.requestActionItemProposals(meetingId, revision),
    onSuccess: () => {
      setNotice(
        'Proposal generation queued. Action items stay unchanged until you approve.',
      );
      onChanged();
    },
    onError: (error) => setNotice(error.message),
  });
  const active = state?.status === 'pending' || state?.status === 'running';
  const capacityBlocked =
    state?.status !== 'done' &&
    state?.error_type === 'ActionItemContextTooLarge';

  return (
    <section
      className="card"
      aria-labelledby="meeting-action-item-proposals-title"
    >
      <h3 className="section-title" id="meeting-action-item-proposals-title">
        Action item proposals
      </h3>
      <p>
        {state ? LABELS[state.status] : 'Loading proposal status…'}
        {state?.status === 'done'
          ? ` · ${state.proposal_count} proposals saved`
          : ''}
      </p>
      {state?.status === 'done' && state.reason && (
        <p className="text-muted-sm">{state.reason}</p>
      )}
      {capacityBlocked && (
        <p className="text-muted-sm" role="status">
          The meeting summary or saved task history is too large to compare
          completely; no partial matching was performed.
        </p>
      )}
      {state?.status === 'failed' && !capacityBlocked && (
        <p className="text-muted-sm">
          Proposal generation could not finish. Retry to continue.
        </p>
      )}
      {state?.status === 'pending' &&
        state.next_attempt_at &&
        state.attempts > 0 && (
          <p className="text-muted-sm">
            Next attempt:{' '}
            <DateCell date={state.next_attempt_at} format="long" />
          </p>
        )}
      <div className="flex-wrap" style={{ gap: 8 }}>
        <button
          className="btn"
          disabled={
            disabled ||
            !state ||
            !state.worker_available ||
            active ||
            request.loading
          }
          onClick={() => request.mutate()}
        >
          {request.loading
            ? 'Queuing…'
            : active
              ? 'Generating proposals…'
              : state?.status === 'failed'
                ? 'Retry proposals'
                : 'Generate proposals'}
        </button>
        <ButtonLink to="/proposals?status=pending">Review proposals</ButtonLink>
      </div>
      {state && !state.worker_available && (
        <p className="text-muted-sm">
          Enable a meeting ingestion job in Jobs to generate proposals.
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
