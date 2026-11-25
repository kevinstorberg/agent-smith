import { useCallback, useRef } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { ActionItemProposal } from '../api';
import { ActionItemProposalContent } from '../components/ActionItemProposalContent';
import { ActionItemProposalSummary } from '../components/ActionItemProposalSummary';
import { ActionItemProposalSupersession } from '../components/ActionItemProposalSupersession';
import {
  ActionItemProposalDecision,
  ActionItemProposalEpicCatalogStatus,
} from '../components/ActionItemProposalDecision';
import { FilterBar } from '../components/FilterBar';
import { Pagination } from '../components/Pagination';
import { DateCell } from '../components/table';
import { ACTION_ITEM_PROPOSAL_STATUSES } from '../constants';
import { useNotification } from '../context/useNotification';
import { useActionItemProposalDecision } from '../hooks/useActionItemProposalDecision';
import { useApiRead } from '../hooks/useApiRead';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { parseViewField } from '../utils/viewPreferences';
import { actionItemProposalDecisionMessage } from '../utils/actionItems';
import './actionItemProposals.css';

export function ActionItemProposalsIndexPage() {
  const preferences = useViewPreferences('actionItemProposals');
  const { q, status } = preferences.values;
  const query = useDebouncedValue(q);
  const { notify } = useNotification();
  const listRef = useRef<HTMLOListElement>(null);
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
  const hasPending = proposals.items.some(
    (proposal) => proposal.status === 'pending',
  );
  const catalog = useApiRead(api.actionItemEpics.list, { enabled: hasPending });
  const refresh = async () => {
    await Promise.all([
      proposals.refresh({ showLoading: false }),
      counts.refresh({ showLoading: false }),
    ]);
  };
  const updating = proposals.loading || !proposals.dataCurrent || q !== query;
  const review = useActionItemProposalDecision({
    refresh,
    focusFallback: listRef,
    canStart: (proposal, action) =>
      !updating &&
      !proposals.error &&
      (action === 'reject' ||
        Boolean(
          proposal.proposed_item &&
          !proposal.source_stale &&
          proposal.source_available !== false &&
          !proposal.target_stale,
        )),
    onSuccess: (result) => {
      proposals.setItems((items) =>
        items.map((item) =>
          item.id === result.id
            ? {
                ...item,
                status: result.status,
                applied_ref: result.applied_ref,
                review_outcome: result.review_outcome,
              }
            : item,
        ),
      );
      notify(actionItemProposalDecisionMessage(result), 'success');
    },
  });
  const pendingId = review.pendingId;
  const busy = pendingId !== null;
  usePolling(refresh, { enabled: !busy });

  return (
    <div className="action-item-proposals-page">
      <div className="page-header">
        <h2 className="page-title">Proposed Action Items</h2>
        <Link className="btn" to="/action-items">
          Saved action items
        </Link>
      </div>
      <p className="action-item-proposal-intro">
        Accept creates a new action item or applies the displayed changes;
        Reject leaves saved items unchanged. No Epic leaves accepted items
        ungrouped.
      </p>
      <FilterBar
        nameValue={q}
        onNameChange={(value) => preferences.setField('q', value)}
        namePlaceholder="Search proposals…"
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
            {ACTION_ITEM_PROPOSAL_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value[0].toUpperCase() + value.slice(1)}
                {counts.data && !counts.error && !q
                  ? ` (${counts.data[value]})`
                  : ''}
              </option>
            ))}
          </select>
        </label>
        {hasPending && (
          <ActionItemProposalEpicCatalogStatus
            catalog={catalog}
            busy={busy}
            onRefresh={() => {
              void Promise.all([catalog.refresh(), refresh()]);
            }}
          />
        )}
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
      {proposals.items.length > 0 && (
        <div className="action-item-proposal-columns" aria-hidden="true">
          <span>Action item</span>
          <span>Project / Tags</span>
          <span>Due date</span>
        </div>
      )}
      <ol
        ref={listRef}
        tabIndex={-1}
        className="action-item-proposal-list"
        aria-label="Proposed Action Items"
        aria-busy={updating}
      >
        {proposals.items.map((proposal) => {
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
              <ActionItemProposalSummary
                proposal={proposal}
                titleId={`proposal-title-${proposal.id}`}
                showStatus={!status || proposal.status !== 'pending'}
                title={
                  <Link
                    className="text-link"
                    to={`/action-items/proposals/${proposal.id}`}
                  >
                    {proposal.target_name}
                  </Link>
                }
              />
              <ActionItemProposalSupersession proposal={proposal} />
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
                <summary>
                  {isCreate
                    ? 'Review proposed item & evidence'
                    : 'Details & evidence'}
                </summary>
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
              <div className="action-item-proposal-actions">
                {proposal.status === 'pending' && (
                  <ActionItemProposalDecision
                    proposal={proposal}
                    catalog={catalog}
                    busy={busy || updating || Boolean(proposals.error)}
                    saving={pendingId === proposal.id}
                    approveDisabled={Boolean(stale) || !proposal.proposed_item}
                    onDecide={(action, placement) => {
                      void review.decide(proposal, action, placement);
                    }}
                  />
                )}
              </div>
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
