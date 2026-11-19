import { useCallback } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { api } from '../api';
import { ActionItemProposalContent } from '../components/ActionItemProposalContent';
import { StatusBadge } from '../components/StatusBadge';
import { useNotification } from '../context/useNotification';
import { useApiMutation } from '../hooks/useApiMutation';
import { useApiRead } from '../hooks/useApiRead';
import { usePageLifetime } from '../hooks/usePageLifetime';
import { usePolling } from '../hooks/usePolling';

export function ActionItemProposalDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isCurrent = usePageLifetime();
  const { notify } = useNotification();
  const read = useApiRead(
    useCallback(() => api.actionItemProposals.get(Number(id)), [id]),
  );
  const review = useApiMutation({
    mutationFn: (action: 'approve' | 'reject') =>
      api.actionItemProposals[action](Number(id)),
    onSuccess: (result) => {
      if (!isCurrent()) return;
      notify(
        result.status === 'approved'
          ? 'Action Item proposal approved'
          : 'Action Item proposal rejected',
        'success',
      );
      read.refresh({ showLoading: false });
    },
    onError: (error) => {
      if (!isCurrent()) return;
      notify(error.message, 'error');
      read.refresh({ showLoading: false });
    },
  });
  const remove = useApiMutation({
    mutationFn: () => api.actionItemProposals.remove(Number(id)),
    onSuccess: () => {
      if (isCurrent()) navigate('/action-items/proposals');
    },
  });
  const busy = review.loading || remove.loading;
  usePolling(() => read.refresh({ showLoading: false }), { enabled: !busy });

  if (read.error)
    return (
      <p role="alert">
        Could not load this Action Item proposal.{' '}
        <button className="btn" onClick={() => read.refresh()}>
          Retry
        </button>
      </p>
    );
  const proposal = read.data;
  if (!proposal) return <p role="status">Loading proposed Action Item…</p>;
  const isUpdate = proposal.action === 'update';
  const targetMissing = isUpdate && !proposal.current_target;
  const targetStale =
    proposal.status === 'pending' &&
    isUpdate &&
    !targetMissing &&
    proposal.current_target?.revision !== proposal.base_version;
  const sourceStale =
    proposal.status === 'pending' &&
    (proposal.source_stale || proposal.source_available === false);

  return (
    <div className="action-item-proposal-detail-page">
      <Link className="text-link" to="/action-items/proposals">
        Proposed Action Items
      </Link>
      <div className="page-header">
        <h2 className="page-title">{proposal.title}</h2>
        <div className="flex-wrap" style={{ gap: 8 }}>
          {proposal.status === 'pending' && (
            <>
              <button
                className="btn btn-primary"
                disabled={
                  busy || targetMissing || targetStale || Boolean(sourceStale)
                }
                onClick={() => review.mutate('approve')}
              >
                Approve
              </button>
              <button
                className="btn"
                disabled={busy}
                onClick={() => review.mutate('reject')}
              >
                Reject
              </button>
            </>
          )}
          <button
            className="btn sidebar-btn-danger"
            disabled={busy}
            onClick={() => {
              if (confirm('Delete this Action Item proposal?')) remove.mutate();
            }}
          >
            Delete proposal
          </button>
        </div>
      </div>
      <section className="card">
        <div className="flex-wrap" style={{ gap: 8 }}>
          <StatusBadge status={proposal.status} kind="proposal" />
          <span className="tag">
            {isUpdate ? 'Update Action Item' : 'New Action Item'}
          </span>
          {proposal.project && (
            <span className="tag tag-project">{proposal.project}</span>
          )}
        </div>
        {targetMissing && (
          <p role="alert">
            The Action Item was deleted. This update can no longer be approved.
          </p>
        )}
        {(targetStale || sourceStale) && (
          <p role="alert">
            {sourceStale
              ? 'The source meeting changed or is unavailable.'
              : 'This action item changed after the proposal was generated.'}{' '}
            Generate a fresh proposal before approving; the reviewed changes
            below are preserved.
          </p>
        )}
        {proposal.applied_ref && (
          <p>
            <Link
              className="text-link"
              to={`/action-items/${proposal.applied_ref.action_item_id}`}
            >
              Open saved action item
            </Link>
          </p>
        )}
      </section>
      <section className="card">
        <h3 className="section-title">Why this Action Item is proposed</h3>
        <p>{proposal.rationale}</p>
      </section>
      <section className="card">
        <h3 className="section-title">Meeting evidence</h3>
        {proposal.evidence.map((entry, index) => (
          <div key={`${entry.id}:${index}`}>
            <Link
              className="text-link"
              to={`/meetings/${encodeURIComponent(entry.id)}`}
            >
              {entry.note || 'Meeting summary'}
            </Link>
            <blockquote
              style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}
            >
              {entry.quote}
            </blockquote>
          </div>
        ))}
      </section>
      <section className="card">
        <h3 className="section-title">
          {isUpdate ? 'Review changes' : 'Review new Action Item'}
        </h3>
        <ActionItemProposalContent
          proposal={proposal}
          targetStale={targetStale}
        />
      </section>
    </div>
  );
}
