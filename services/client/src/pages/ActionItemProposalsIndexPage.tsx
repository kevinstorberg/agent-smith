import { useCallback } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { ActionItemProposal } from '../api';
import { FilterBar } from '../components/FilterBar';
import { Pagination } from '../components/Pagination';
import { StatusBadge } from '../components/StatusBadge';
import { DateCell } from '../components/table';
import { PROPOSAL_STATUSES } from '../constants';
import { useApiRead } from '../hooks/useApiRead';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { useViewPreferences } from '../hooks/useViewPreferences';

export function ActionItemProposalsIndexPage() {
  const preferences = useViewPreferences('actionItemProposals');
  const { q, status } = preferences.values;
  const query = useDebouncedValue(q);
  const proposals = usePagination<ActionItemProposal>(
    (limit, offset) =>
      api.actionItemProposals.list(status || undefined, {
        q: query || undefined,
        limit,
        offset,
      }),
    [status, query],
    10,
    { ...preferences.pagination, enabled: q === query },
  );
  const counts = useApiRead(
    useCallback(() => api.actionItemProposals.counts(), []),
  );
  usePolling(async () => {
    await Promise.all([
      proposals.refresh({ showLoading: false }),
      counts.refresh({ showLoading: false }),
    ]);
  });
  const updating = proposals.loading || !proposals.dataCurrent || q !== query;

  return (
    <div className="action-item-proposals-page">
      <div className="page-header">
        <h2 className="page-title">Proposed Action Items</h2>
        <Link className="btn" to="/action-items">
          Saved action items
        </Link>
      </div>
      <p>
        Review new Action Items and suggested updates before they change your
        list.
      </p>
      <FilterBar
        nameValue={q}
        onNameChange={(value) => preferences.setField('q', value)}
        namePlaceholder="Search proposed action items..."
      >
        <div
          className="filter-status-group"
          role="group"
          aria-label="Action Item proposal status"
        >
          {(['', ...PROPOSAL_STATUSES] as const).map((value) => (
            <button
              key={value}
              className={`btn${status === value ? ' btn-primary' : ''}`}
              aria-pressed={status === value}
              onClick={() => preferences.setField('status', value)}
            >
              {value || 'All statuses'}
              {value && counts.data && !q ? ` (${counts.data[value]})` : ''}
            </button>
          ))}
        </div>
      </FilterBar>
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
        aria-label="Proposed Action Items"
        aria-busy={updating}
        style={{ listStyle: 'none', padding: 0 }}
      >
        {!proposals.error &&
          proposals.items.map((proposal) => (
            <li
              key={proposal.id}
              className="card"
              style={{ overflowWrap: 'anywhere' }}
            >
              <div className="flex-wrap" style={{ gap: 8 }}>
                <span className="tag">
                  {proposal.action === 'create'
                    ? 'New Action Item'
                    : 'Suggested update'}
                </span>
                <StatusBadge status={proposal.status} kind="proposal" />
                {proposal.project && (
                  <span className="tag tag-project">{proposal.project}</span>
                )}
              </div>
              <h3>
                <Link
                  className="text-link"
                  to={`/action-items/proposals/${proposal.id}`}
                >
                  {proposal.target_name}
                </Link>
              </h3>
              <p>{proposal.rationale}</p>
              <div className="flex-wrap" style={{ gap: 12 }}>
                <Link
                  className="btn"
                  to={`/action-items/proposals/${proposal.id}`}
                >
                  Review{' '}
                  {proposal.action === 'create' ? 'new Action Item' : 'changes'}
                </Link>
                <span className="text-muted-sm">
                  <DateCell date={proposal.created_at} format="long" />
                </span>
              </div>
            </li>
          ))}
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
