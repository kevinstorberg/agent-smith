import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { Proposal, ProposalCounts } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { DateCell } from '../components/table';
import { ScrollableTable } from '../components/ScrollableTable';
import { SortableHeader } from '../components/table/SortableHeader';
import { useNotification } from '../context/useNotification';
import { usePagination } from '../hooks/usePagination';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { PROPOSAL_SORT_COLUMNS, PROPOSAL_STATUSES } from '../constants';
import { useViewPreferences } from '../hooks/useViewPreferences';
import './proposalsSorting.css';

export function ProposalsIndexPage() {
  const preferences = useViewPreferences('proposals');
  const { status: statusFilter, q: query, sort } = preferences.values;
  const debouncedQuery = useDebouncedValue(query);
  const [counts, setCounts] = useState<ProposalCounts | null>(null);
  const [generating, setGenerating] = useState(false);
  const navigate = useNavigate();
  const { notify } = useNotification();

  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const {
    items,
    total,
    loading,
    initialLoading,
    error,
    dataCurrent,
    limit,
    offset,
    setLimit,
    setOffset,
    refresh,
  } = usePagination<Proposal>(
    (l, o) =>
      api.proposals.list(statusFilter || undefined, {
        limit: l,
        offset: o,
        q: debouncedQuery || undefined,
        sort,
      }),
    [statusFilter, debouncedQuery, sort],
    10,
    { ...preferences.pagination, enabled: debouncedQuery === query },
  );
  const latestRefresh = useRef(refresh);
  const mounted = useRef(false);
  useEffect(() => {
    latestRefresh.current = refresh;
  }, [refresh]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const loadCounts = useCallback(async () => {
    try {
      setCounts(await api.proposals.counts());
    } catch {
      setCounts(null);
    }
  }, []);

  useEffect(() => {
    loadCounts();
  }, [loadCounts]);
  usePolling(
    async () => {
      await Promise.all([refresh({ showLoading: false }), loadCounts()]);
    },
    { enabled: busyIds.size === 0 },
  );
  const updating =
    loading || (!error && !dataCurrent) || query !== debouncedQuery;
  const accepted = !error && !updating;

  async function quickReview(proposal: Proposal, action: 'approve' | 'reject') {
    setBusyIds((prev) => new Set(prev).add(proposal.id));
    try {
      await api.proposals[action](proposal.id);
      if (!mounted.current) return;
      await latestRefresh.current({ showLoading: false });
      await loadCounts();
      if (mounted.current)
        notify(
          `${proposal.target_name}: ${action === 'approve' ? 'applied' : 'rejected'}`,
          'success',
        );
    } catch (err) {
      if (mounted.current)
        notify(
          `${action} failed: ${err instanceof Error ? err.message : String(err)}`,
          'error',
        );
    } finally {
      if (mounted.current)
        setBusyIds((prev) => {
          const next = new Set(prev);
          next.delete(proposal.id);
          return next;
        });
    }
  }

  async function handleGenerate() {
    setGenerating(true);
    try {
      await api.proposals.generate();
      if (mounted.current)
        notify(
          'Generation started — refresh shortly; run status is under Jobs',
          'success',
        );
    } catch (err) {
      if (mounted.current)
        notify(
          `Generate failed: ${err instanceof Error ? err.message : String(err)}`,
          'error',
        );
    } finally {
      if (mounted.current) setGenerating(false);
    }
  }

  return (
    <div className="proposals-page">
      <div className="page-header">
        <h2 className="page-title">Proposals</h2>
        <button
          className="btn btn-primary"
          onClick={handleGenerate}
          disabled={generating}
        >
          {generating ? 'Starting...' : 'Generate now'}
        </button>
      </div>

      <FilterBar
        nameValue={query}
        onNameChange={(value) => preferences.setField('q', value)}
        namePlaceholder="Search proposals..."
      >
        <div
          className="filter-status-group"
          role="group"
          aria-label="Proposal status"
        >
          <button
            className={`btn${statusFilter === '' ? ' btn-primary' : ''}`}
            aria-pressed={statusFilter === ''}
            onClick={() => preferences.setField('status', '')}
          >
            all statuses
          </button>
          {PROPOSAL_STATUSES.map((status) => (
            <button
              key={status}
              className={`btn${statusFilter === status ? ' btn-primary' : ''}`}
              aria-pressed={statusFilter === status}
              onClick={() => preferences.setField('status', status)}
            >
              {status}
              {!query && !debouncedQuery && counts
                ? ` (${counts[status]})`
                : ''}
            </button>
          ))}
        </div>
      </FilterBar>

      {error && (
        <p role="alert">
          Could not load proposals.{' '}
          <button className="btn btn-sm" onClick={() => refresh()}>
            Retry
          </button>
        </p>
      )}
      {initialLoading && (
        <div className="loading" role="status">
          Loading...
        </div>
      )}
      <span className="visually-hidden" role="status">
        {!initialLoading && updating ? 'Updating proposals…' : ''}
      </span>
      <ScrollableTable
        label="Proposals list"
        className="proposals-list-table"
        busy={updating && (loading || !error)}
        emptyState={
          accepted && items.length === 0 ? (
            <p className="loading" role="status">
              No {statusFilter ? `${statusFilter} ` : ''}proposals
            </p>
          ) : undefined
        }
      >
        <thead>
          <tr>
            {(
              [
                ['Title', 'title'],
                ['Kind', 'kind'],
                ['Action', 'action'],
                ['Target', 'target'],
                ['Created', 'created'],
              ] as const
            ).map(([label, key]) => (
              <SortableHeader
                key={key}
                sort={sort}
                column={PROPOSAL_SORT_COLUMNS[key]}
                current={accepted}
                onSort={(value) => preferences.setField('sort', value)}
              >
                {label}
              </SortableHeader>
            ))}
            <th style={{ textAlign: 'right' }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {!error &&
            items.map((proposal) => {
              const busy = busyIds.has(proposal.id);
              return (
                <tr
                  key={proposal.id}
                  {...makeRowClickable(() =>
                    navigate(`/proposals/${proposal.id}`),
                  )}
                  style={{ cursor: 'pointer' }}
                >
                  <td>{proposal.title}</td>
                  <td>
                    <span className="tag">{proposal.target_kind}</span>
                  </td>
                  <td>{proposal.action}</td>
                  <td>{proposal.target_name}</td>
                  <td>
                    <DateCell date={proposal.created_at} />
                  </td>
                  <td
                    style={{ textAlign: 'right', whiteSpace: 'nowrap' }}
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    {proposal.status === 'pending' ? (
                      <>
                        <button
                          className="btn btn-sm btn-primary"
                          disabled={busy || !accepted}
                          onClick={() => quickReview(proposal, 'approve')}
                        >
                          Approve
                        </button>{' '}
                        <button
                          className="btn btn-sm"
                          disabled={busy || !accepted}
                          onClick={() => quickReview(proposal, 'reject')}
                        >
                          Reject
                        </button>
                      </>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>—</span>
                    )}
                  </td>
                </tr>
              );
            })}
        </tbody>
      </ScrollableTable>

      {!error && (
        <Pagination
          total={total}
          limit={limit}
          offset={offset}
          onPageChange={setOffset}
          onLimitChange={(newLimit) => {
            setLimit(newLimit);
            setOffset(0);
          }}
          disabled={loading}
        />
      )}
    </div>
  );
}
