import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { Proposal, ProposalCounts } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { DateCell } from '../components/table';
import { ScrollableTable } from '../components/ScrollableTable';
import { useNotification } from '../context/useNotification';
import { usePagination } from '../hooks/usePagination';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { PROPOSAL_SORT_OPTIONS, PROPOSAL_STATUSES } from '../constants';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { parseViewField } from '../utils/viewPreferences';

export function ProposalsIndexPage() {
  const preferences = useViewPreferences('proposals');
  const { status: statusFilter, q: query, sort } = preferences.values;
  const debouncedQuery = useDebouncedValue(query);
  const [counts, setCounts] = useState<ProposalCounts | null>(null);
  const [generating, setGenerating] = useState(false);
  const navigate = useNavigate();
  const { notify } = useNotification();

  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const { items, total, loading, error, limit, offset, setLimit, setOffset, refresh } = usePagination<Proposal>(
    (l, o) => api.proposals.list(statusFilter || undefined, { limit: l, offset: o, q: debouncedQuery || undefined, sort }),
    [statusFilter, debouncedQuery, sort],
    10, { ...preferences.pagination, enabled: debouncedQuery === query },
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

      <FilterBar nameValue={query} onNameChange={value => preferences.setField('q', value)} namePlaceholder="Search proposals..." onReset={preferences.reset}>
        <label><span className="form-label">Sort proposals</span>
        <select aria-label="Sort proposals" value={sort} onChange={event => preferences.setField('sort', parseViewField('proposals', 'sort', event.target.value))}>
          {PROPOSAL_SORT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        </label>
      </FilterBar>
      <div className="filters">
        <button className={`btn${statusFilter === '' ? ' btn-primary' : ''}`}
          onClick={() => preferences.setField('status', '')}>all statuses</button>
        {PROPOSAL_STATUSES.map(status => (
          <button
            key={status}
            className={`btn${statusFilter === status ? ' btn-primary' : ''}`}
            onClick={() => preferences.setField('status', status)}
          >
            {status}{!query && !debouncedQuery && counts ? ` (${counts[status]})` : ''}
          </button>
        ))}
      </div>

      {error && <p role="alert">Could not load proposals. <button className="btn btn-sm" onClick={() => refresh()}>Retry</button></p>}
      {loading && <div className="loading" role="status">Loading...</div>}
      <ScrollableTable label="Proposals list" className="proposals-list-table" empty={items.length === 0}>
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
      </ScrollableTable>

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
