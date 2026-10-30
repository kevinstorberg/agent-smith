import { useState } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { Plan } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { DateCell } from '../components/table';
import { StatusBadge } from '../components/StatusBadge';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { useDebouncedValue } from '../hooks/useDebouncedValue';

const STATUSES = ['all', 'draft', 'final'] as const;

export function PlansIndexPage() {
  const [projectInput, setProjectInput] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const projectFilter = useDebouncedValue(projectInput.trim());
  const debouncedSearch = useDebouncedValue(searchQuery.trim());
  const searchTerm = searchQuery.trim() ? debouncedSearch : '';
  const navigate = useNavigate();

  const { items, total, loading, error, limit, offset, setLimit, setOffset, refresh } = usePagination<Plan>(
    async (limit, offset) => {
      const filters = { project: projectFilter || undefined, status: statusFilter === 'all' ? undefined : statusFilter };
      if (searchTerm) {
        const matches = await api.plans.search(searchTerm, filters);
        return { items: matches.slice(offset, offset + limit), total: matches.length };
      }
      return api.plans.list({ limit, offset, ...filters });
    },
    [searchTerm, projectFilter, statusFilter],
  );
  usePolling(() => refresh({ showLoading: false }));

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Plans</h2>
        <button className="btn btn-primary" onClick={() => navigate('/plans/new')}>
          + New Plan
        </button>
      </div>

      <FilterBar
        nameValue={searchQuery}
        projectValue={projectInput}
        onNameChange={setSearchQuery}
        onProjectChange={setProjectInput}
        namePlaceholder="Search by title..."
      />

      <div className="filters">
          {STATUSES.map(status => (
            <button
              key={status}
              className={`btn${statusFilter === status ? ' btn-primary' : ''}`}
              onClick={() => { setStatusFilter(status); setOffset(0); }}
            >
              {status}
            </button>
          ))}
      </div>

      {loading && <div className="loading">Loading...</div>}
      {error && <div role="alert" className="card">Could not load plans. <button className="btn" onClick={() => refresh()}>Retry</button></div>}

      <div className="table-container plans-table">
        <table className="table">
          <colgroup>
            <col />
            <col className="plans-status-column" />
            <col className="plans-project-column" />
            <col className="plans-date-column" />
          </colgroup>
          <thead>
            <tr>
              <th>Title</th>
              <th>Status</th>
              <th>Project</th>
              <th>Last Updated</th>
            </tr>
          </thead>
          <tbody>
            {!loading && !error && items.map(plan => (
              <tr
                key={plan.id}
                {...makeRowClickable(() => navigate(`/plans/${plan.id}`))}
                style={{ cursor: 'pointer' }}
              >
                <td>{plan.title}</td>
                <td><StatusBadge status={plan.status} kind="plan" /></td>
                <td>
                  {plan.project ? (
                    <span className="tag tag-project">{plan.project}</span>
                  ) : (
                    <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>--</span>
                  )}
                </td>
                <td><DateCell date={plan.updated_at} /></td>
              </tr>
            ))}
            {!loading && !error && items.length === 0 && (
              <tr><td colSpan={4} className="loading">No plans found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {!loading && !error && (
        <Pagination
          total={total}
          limit={limit}
          offset={offset}
          onPageChange={setOffset}
          onLimitChange={newLimit => { setLimit(newLimit); setOffset(0); }}
        />
      )}
    </div>
  );
}
