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

  const { items, total, loading, limit, offset, setLimit, setOffset } = usePagination<Proposal>(
    (l, o) => api.proposals.list(statusFilter || undefined, { limit: l, offset: o }),
    [statusFilter],
  );

  useEffect(() => {
    api.proposals.counts().then(setCounts).catch(() => setCounts(null));
  }, [items]);

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
          </tr>
        </thead>
        <tbody>
          {items.map(proposal => (
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
            </tr>
          ))}
          {items.length === 0 && (
            <tr><td colSpan={5} className="loading">No {statusFilter} proposals</td></tr>
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
