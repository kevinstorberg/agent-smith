import { useCallback, useRef } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { api } from '../api';
import { ActionItemProposalContent } from '../components/ActionItemProposalContent';
import { ActionItemProposalSupersession } from '../components/ActionItemProposalSupersession';
import {
  ActionItemProposalDecision,
  ActionItemProposalEpicCatalogStatus,
} from '../components/ActionItemProposalDecision';
import { useActionItemProposalDecision } from '../hooks/useActionItemProposalDecision';
import { ActionItemProposalSummary } from '../components/ActionItemProposalSummary';
import { useNotification } from '../context/useNotification';
import { useApiMutation } from '../hooks/useApiMutation';
import { useApiRead } from '../hooks/useApiRead';
import { usePageLifetime } from '../hooks/usePageLifetime';
import { usePolling } from '../hooks/usePolling';
import './actionItemProposals.css';

export function ActionItemProposalDetailPage() {
  const { id } = useParams();
  return <ActionItemProposalDetail key={id} id={Number(id)} />;
}

function ActionItemProposalDetail({ id }: { id: number }) {
  const navigate = useNavigate();
  const isCurrent = usePageLifetime();
  const { notify } = useNotification();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const read = useApiRead(
    useCallback(() => api.actionItemProposals.get(Number(id)), [id]),
  );
  const remove = useApiMutation({
    mutationFn: () => api.actionItemProposals.remove(Number(id)),
    onSuccess: () => {
      if (isCurrent()) navigate('/action-items/proposals');
    },
  });
  const catalog = useApiRead(api.actionItemEpics.list, {
    enabled: read.data?.status === 'pending',
  });
  const review = useActionItemProposalDecision({
    refresh: () => read.refresh({ showLoading: false }),
    focusFallback: titleRef,
    canStart: (proposal, action) =>
      !remove.loading &&
      !read.loading &&
      !read.error &&
      (action === 'reject' ||
        Boolean(
          proposal.proposed_item &&
          !proposal.source_stale &&
          proposal.source_available !== false &&
          !proposal.target_stale &&
          (proposal.action !== 'update' ||
            (proposal.current_target &&
              proposal.current_target.revision === proposal.base_version)),
        )),
    onSuccess: (result) => {
      if (!isCurrent()) return;
      notify(
        result.status === 'approved'
          ? 'Action Item proposal approved'
          : 'Action Item proposal rejected',
        'success',
      );
    },
  });
  const busy = review.pendingId !== null || remove.loading;
  usePolling(() => read.refresh({ showLoading: false }), { enabled: !busy });

  if (read.error && !read.data)
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
        <h2 className="page-title" tabIndex={-1} ref={titleRef}>
          {proposal.title}
        </h2>
        <div className="flex-wrap" style={{ gap: 8 }}>
          <button
            className="btn sidebar-btn-danger"
            disabled={busy}
            onClick={() => {
              if (busy || review.isWriting()) return;
              if (confirm('Delete this Action Item proposal?')) remove.mutate();
            }}
          >
            Delete proposal
          </button>
        </div>
      </div>
      {review.error && (
        <p role="alert">
          Could not decide this Action Item: {review.error.message}
        </p>
      )}
      {read.error && (
        <p role="alert">
          Could not refresh this Action Item proposal.{' '}
          <button className="btn" onClick={() => read.refresh()}>
            Retry
          </button>
        </p>
      )}
      <section className="card">
        <ActionItemProposalSummary
          proposal={proposal}
          title={proposal.target_name}
          showStatus
        />
        <ActionItemProposalSupersession proposal={proposal} />
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
        <h3 className="section-title">
          {isUpdate ? 'Review changes' : 'Review new Action Item'}
        </h3>
        {proposal.status === 'pending' && (
          <p className="action-item-proposal-effect">
            {isUpdate
              ? 'Accept applies these changes to the existing action item.'
              : 'Accept creates this action item.'}
          </p>
        )}
        <ActionItemProposalContent
          proposal={proposal}
          targetStale={targetStale}
        />
        {proposal.status === 'pending' && (
          <div className="action-item-proposal-review-footer">
            <ActionItemProposalDecision
              proposal={proposal}
              catalog={catalog}
              busy={busy || read.loading || Boolean(read.error)}
              saving={review.pendingId === proposal.id}
              approveDisabled={
                targetMissing ||
                targetStale ||
                Boolean(sourceStale) ||
                Boolean(proposal.target_stale) ||
                !proposal.proposed_item
              }
              onDecide={(action, placement) => {
                void review.decide(proposal, action, placement);
              }}
            />
            <ActionItemProposalEpicCatalogStatus
              catalog={catalog}
              busy={busy}
              onRefresh={() => {
                void Promise.all([
                  catalog.refresh(),
                  read.refresh({ showLoading: false }),
                ]);
              }}
            />
          </div>
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
    </div>
  );
}
