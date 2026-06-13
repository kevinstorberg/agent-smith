import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { Proposal, ProposalCounts } from '../api';
import { Pagination } from '../components/Pagination';
import { DateCell } from '../components/table';
import { useNotification } from '../context/useNotification';
import { usePagination } from '../hooks/usePagination';
import { makeRowClickable } from '../utils/a11y';

const STATUSES = ['pending', 'approved', 'rejected'] as const;

export function ProposalsIndexPage() {
  const [statusFilter, setStatusFilter] = useState<string>('pending');
  const [counts, setCounts] = useState<ProposalCounts | null>(null);
  const [generating, setGenerating] = useState(false);
  const navigate = useNavigate();
  const { notify } = useNotification();

  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const { items, setItems, total, loading, limit, offset, setLimit, setOffset } = usePagination<Proposal>(
    (l, o) => api.proposals.list(statusFilter || undefined, { limit: l, offset: o }),
    [statusFilter],
  );

  useEffect(() => {
    api.proposals.counts().then(setCounts).catch(() => setCounts(null));
  }, [items]);

  async function quickReview(proposal: Proposal, action: 'approve' | 'reject') {
    setBusyIds(prev => new Set(prev).add(proposal.id));
    try {
      await api.proposals[action](proposal.id);
      setItems(prev => prev.filter(p => p.id !== proposal.id));
      notify(`${proposal.target_name}: ${action === 'approve' ? 'applied' : 'rejected'}`, 'success');
    } catch (err) {
      notify(`${action} failed: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setBusyIds(prev => {
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
      notify('Generation started — refresh shortly; run status is under Jobs', 'success');
    } catch (err) {
      notify(`Generate failed: ${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setGenerating(false);
    }
  }

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Proposals</h2>
        <button className="btn btn-primary" onClick={handleGenerate} disabled={generating}>
          {generating ? 'Starting...' : 'Generate now'}
        </button>
      </div>

      <div className="filters">
        {STATUSES.map(status => (
          <button
            key={status}
            className={`btn${statusFilter === status ? ' btn-primary' : ''}`}
            onClick={() => { setStatusFilter(status); setOffset(0); }}
          >
            {status}{counts ? ` (${counts[status]})` : ''}
          </button>
        ))}
      </div>

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
          {items.map(proposal => {
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
          {items.length === 0 && (
            <tr><td colSpan={6} className="loading">No {statusFilter} proposals</td></tr>
          )}
        </tbody>
      </table>

      <Pagination
        total={total}
        limit={limit}
        offset={offset}
        onPageChange={setOffset}
        onLimitChange={newLimit => { setLimit(newLimit); setOffset(0); }}
      />
    </div>
  );
}
