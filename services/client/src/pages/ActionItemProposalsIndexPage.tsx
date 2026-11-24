import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { ActionItemProposal } from '../api';
import { ActionItemProposalContent } from '../components/ActionItemProposalContent';
import { FilterBar } from '../components/FilterBar';
import { Pagination } from '../components/Pagination';
import { DateCell } from '../components/table';
import { PROPOSAL_STATUSES } from '../constants';
import { useNotification } from '../context/useNotification';
import { useApiMutation } from '../hooks/useApiMutation';
import { useApiRead } from '../hooks/useApiRead';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { usePageLifetime } from '../hooks/usePageLifetime';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { parseViewField } from '../utils/viewPreferences';
import './actionItemProposals.css';

export function ActionItemProposalsIndexPage() {
  const preferences = useViewPreferences('actionItemProposals');
  const { q, status } = preferences.values;
  const query = useDebouncedValue(q);
  const isCurrent = usePageLifetime();
  const { notify } = useNotification();
  const writing = useRef(false);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const proposals = usePagination<ActionItemProposal>(
    (limit, offset) =>
      api.actionItemProposals.list(status || undefined, {
        q: query || undefined,
        limit,
        offset,
      }),
    [status, query],
    10,
    { ...preferences.pagination, enabled: q === query, clampOffset: true },
  );
  const counts = useApiRead(
    useCallback(() => api.actionItemProposals.counts(), []),
  );
  const refresh = async () => {
    await Promise.all([
      proposals.refresh({ showLoading: false }),
      counts.refresh({ showLoading: false }),
    ]);
  };
  const latestRefresh = useRef(refresh);
  useLayoutEffect(() => {
    latestRefresh.current = refresh;
  });
  usePolling(refresh, { enabled: pendingId === null });
  const updating = proposals.loading || !proposals.dataCurrent || q !== query;
  const busy = pendingId !== null;
  const review = useApiMutation({
    mutationFn: (proposal: ActionItemProposal, action: 'approve' | 'reject') =>
      api.actionItemProposals[action](proposal.id),
    onSuccess: (result) => {
      if (!isCurrent()) return;
      proposals.setItems((items) =>
        items.map((item) =>
          item.id === result.id ? { ...item, status: result.status } : item,
        ),
      );
      notify(
        result.status === 'approved'
          ? 'Action Item accepted'
          : 'Action Item rejected',
        'success',
      );
    },
    // The persistent inline alert is the sole review-failure channel.
    onError: () => undefined,
  });

  async function decide(
    proposal: ActionItemProposal,
    action: 'approve' | 'reject',
  ) {
    if (writing.current || updating || proposal.status !== 'pending') return;
    writing.current = true;
    setPendingId(proposal.id);
    try {
      await review.mutate(proposal, action);
      if (isCurrent()) await latestRefresh.current();
    } finally {
      writing.current = false;
      if (isCurrent()) setPendingId(null);
    }
  }

  return (
    <div className="action-item-proposals-page">
      <div className="page-header">
        <h2 className="page-title">Proposed Action Items</h2>
        <Link className="btn" to="/action-items">
          Saved action items
        </Link>
      </div>
      <FilterBar
        nameValue={q}
        onNameChange={(value) => preferences.setField('q', value)}
        namePlaceholder="Search proposed action items..."
      >
        <label>
          <span className="form-label">Status</span>
          <select
            className="input"
            value={status}
            onChange={(event) =>
              preferences.setField(
                'status',
                parseViewField(
                  'actionItemProposals',
                  'status',
                  event.target.value,
                ),
              )
            }
          >
            <option value="">All statuses</option>
            {PROPOSAL_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value[0].toUpperCase() + value.slice(1)}
                {counts.data && !counts.error && !q
                  ? ` (${counts.data[value]})`
                  : ''}
              </option>
            ))}
          </select>
        </label>
      </FilterBar>
      {review.error && (
        <p role="alert">
          Could not decide this Action Item: {review.error.message}
        </p>
      )}
      {proposals.error && (
        <p role="alert">
          Could not load proposed Action Items.{' '}
          <button className="btn" onClick={() => proposals.refresh()}>
            Retry
          </button>
        </p>
      )}
      {proposals.initialLoading && (
        <p role="status">Loading proposed Action Items…</p>
      )}
      {!proposals.error && !updating && proposals.items.length === 0 && (
        <section className="card" role="status">
          <h3>No {status ? `${status} ` : ''}proposed Action Items</h3>
          <p>New meeting summaries can propose Action Items automatically.</p>
          <p>
            For an existing meeting, open its Overview and choose{' '}
            <strong>Propose action items</strong>.
          </p>
          <Link className="text-link" to="/meetings">
            Open meetings
          </Link>
        </section>
      )}
      <ol
        className="action-item-proposal-list"
        aria-label="Proposed Action Items"
        aria-busy={updating}
      >
        {!proposals.error &&
          proposals.items.map((proposal) => {
            const stale =
              proposal.source_stale ||
              proposal.source_available === false ||
              proposal.target_stale;
            const isCreate = proposal.action === 'create';
            return (
              <li
                key={proposal.id}
                className="action-item-proposal-row"
                aria-labelledby={`proposal-title-${proposal.id}`}
              >
                <div className="action-item-proposal-heading">
                  <div className="action-item-proposal-identity">
                    <h3 id={`proposal-title-${proposal.id}`}>
                      <Link
                        className="text-link"
                        to={`/action-items/proposals/${proposal.id}`}
                      >
                        {proposal.target_name}
                      </Link>
                    </h3>
                    <div className="action-item-proposal-metadata">
                      <span>{isCreate ? 'New' : 'Update'}</span>
                      {proposal.project && <span>{proposal.project}</span>}
                      {(!status || proposal.status !== 'pending') && (
                        <span>{proposal.status}</span>
                      )}
                      {isCreate && proposal.proposed_item?.due_at && (
                        <div className="action-item-proposal-deadline">
                          Due{' '}
                          <DateCell
                            date={proposal.proposed_item.due_at}
                            format="long"
                          />
                        </div>
                      )}
                      {isCreate &&
                        proposal.proposed_item?.status &&
                        proposal.proposed_item.status !== 'open' && (
                          <span>
                            Creates {proposal.proposed_item.status} item
                          </span>
                        )}
                    </div>
                  </div>
                  <div className="action-item-proposal-actions">
                    {proposal.status === 'pending' && (
                      <>
                        <button
                          className="btn btn-primary"
                          disabled={
                            busy ||
                            updating ||
                            Boolean(stale) ||
                            !proposal.proposed_item
                          }
                          onClick={() => decide(proposal, 'approve')}
                        >
                          {pendingId === proposal.id ? 'Saving…' : 'Accept'}
                        </button>
                        <button
                          className="btn"
                          disabled={busy || updating}
                          onClick={() => decide(proposal, 'reject')}
                        >
                          Reject
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {proposal.status === 'pending' && stale && (
                  <p role="alert">
                    The source meeting or saved Action Item changed or is
                    unavailable; generate a fresh proposal before accepting.
                  </p>
                )}
                {!isCreate && proposal.proposed_item && (
                  <ActionItemProposalContent
                    proposal={proposal}
                    targetStale={false}
                    compact
                  />
                )}
                <details className="action-item-proposal-details">
                  <summary>Details &amp; evidence</summary>
                  <div className="action-item-proposal-context">
                    {isCreate && proposal.proposed_item && (
                      <ActionItemProposalContent
                        proposal={proposal}
                        targetStale={false}
                        compact
                        omitCreateTitle
                      />
                    )}
                    <p>{proposal.rationale}</p>
                    {proposal.evidence.map((entry, index) => (
                      <blockquote key={`${entry.id}:${index}`}>
                        {entry.quote}
                      </blockquote>
                    ))}
                    <div className="action-item-proposal-created">
                      Proposed{' '}
                      <DateCell date={proposal.created_at} format="long" />
                    </div>
                  </div>
                </details>
              </li>
            );
          })}
      </ol>
      <Pagination
        total={proposals.total}
        limit={proposals.limit}
        offset={proposals.offset}
        onPageChange={proposals.setOffset}
        onLimitChange={proposals.setLimit}
        disabled={updating}
      />
    </div>
  );
}
