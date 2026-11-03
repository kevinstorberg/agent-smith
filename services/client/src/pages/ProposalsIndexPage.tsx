import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { Proposal, ProposalCounts } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { DateCell } from '../components/table';
import { useNotification } from '../context/useNotification';
import { usePagination } from '../hooks/usePagination';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';

const STATUSES = ['pending', 'approved', 'rejected'] as const;

export function ProposalsIndexPage() {
  const [statusFilter, setStatusFilter] = useState<string>('pending');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<'newest' | 'oldest' | 'title'>('newest');
  const debouncedQuery = useDebouncedValue(query);
  const [counts, setCounts] = useState<ProposalCounts | null>(null);
  const [generating, setGenerating] = useState(false);
  const navigate = useNavigate();
  const { notify } = useNotification();

  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const { items, total, loading, error, limit, offset, setLimit, setOffset, refresh } = usePagination<Proposal>(
    (l, o) => api.proposals.list(statusFilter || undefined, { limit: l, offset: o, q: debouncedQuery || undefined, sort }),
    [statusFilter, debouncedQuery, sort],
  );
  const latestRefresh = useRef(refresh);
  const mounted = useRef(false);
  useEffect(() => { latestRefresh.current = refresh; }, [refresh]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
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
      await Promise.all([
        refresh({ showLoading: false }),
        loadCounts(),
      ]);
    },
    { enabled: busyIds.size === 0 },
  );

  async function quickReview(proposal: Proposal, action: 'approve' | 'reject') {
    setBusyIds(prev => new Set(prev).add(proposal.id));
    try {
      await api.proposals[action](proposal.id);
      if (!mounted.current) return;
      await latestRefresh.current({ showLoading: false });
      await loadCounts();
      if (mounted.current) notify(`${proposal.target_name}: ${action === 'approve' ? 'applied' : 'rejected'}`, 'success');
    } catch (err) {
      if (mounted.current) notify(`${action} failed: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      if (mounted.current) setBusyIds(prev => {
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
      if (mounted.current) notify('Generation started — refresh shortly; run status is under Jobs', 'success');
    } catch (err) {
      if (mounted.current) notify(`Generate failed: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      if (mounted.current) setGenerating(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Proposals</h2>
        <button className="btn btn-primary" onClick={handleGenerate} disabled={generating}>
          {generating ? 'Starting...' : 'Generate now'}
        </button>
      </div>

      <FilterBar nameValue={query} onNameChange={setQuery} namePlaceholder="Search proposals...">
        <label><span className="form-label">Sort proposals</span>
        <select aria-label="Sort proposals" value={sort} onChange={event => setSort(event.target.value as typeof sort)}>
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="title">Title</option>
        </select>
        </label>
      </FilterBar>
      <div className="filters">
        <button className={`btn${statusFilter === '' ? ' btn-primary' : ''}`}
          onClick={() => { setStatusFilter(''); setOffset(0); }}>all statuses</button>
        {STATUSES.map(status => (
          <button
            key={status}
            className={`btn${statusFilter === status ? ' btn-primary' : ''}`}
            onClick={() => { setStatusFilter(status); setOffset(0); }}
          >
            {status}{!query && !debouncedQuery && counts ? ` (${counts[status]})` : ''}
          </button>
        ))}
      </div>

      {error && <p role="alert">Could not load proposals. <button className="btn btn-sm" onClick={() => refresh()}>Retry</button></p>}
      {loading && <div className="loading" role="status">Loading...</div>}
      <table className="table">
        <thead>
          <tr>
            <th>Title</th>
            <th>Kind</th>
            <th>Action</th>
            <th>Target</th>
            <th>Created</th>
            <th style={{ textAlign: 'right' }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {!loading && !error && items.map(proposal => {
            const busy = busyIds.has(proposal.id);
            return (
              <tr
                key={proposal.id}
                {...makeRowClickable(() => navigate(`/proposals/${proposal.id}`))}
                style={{ cursor: 'pointer' }}
              >
                <td>{proposal.title}</td>
                <td><span className="tag">{proposal.target_kind}</span></td>
                <td>{proposal.action}</td>
                <td>{proposal.target_name}</td>
                <td><DateCell date={proposal.created_at} /></td>
                <td
                  style={{ textAlign: 'right', whiteSpace: 'nowrap' }}
                  onClick={e => e.stopPropagation()}
                  onKeyDown={e => e.stopPropagation()}
                >
                  {proposal.status === 'pending' ? (
                    <>
                      <button
                        className="btn btn-sm btn-primary"
                        disabled={busy}
                        onClick={() => quickReview(proposal, 'approve')}
                      >
                        Approve
                      </button>{' '}
                      <button
                        className="btn btn-sm"
                        disabled={busy}
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
          {!loading && !error && items.length === 0 && (
            <tr><td colSpan={6} className="loading">No {statusFilter ? `${statusFilter} ` : ''}proposals</td></tr>
          )}
        </tbody>
      </table>

      {!error && <Pagination
        total={total}
        limit={limit}
        offset={offset}
        onPageChange={setOffset}
        onLimitChange={newLimit => { setLimit(newLimit); setOffset(0); }}
        disabled={loading}
      />}
    </div>
  );
}
