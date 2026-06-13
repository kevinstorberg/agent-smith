import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { Plan } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { DateCell } from '../components/table';
import { usePagination } from '../hooks/usePagination';
import { makeRowClickable } from '../utils/a11y';

const STATUSES = ['all', 'draft', 'final'] as const;

export function PlansIndexPage() {
  const [projectFilter, setProjectFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Plan[] | null>(null);
  const navigate = useNavigate();

  const { items, total, loading, limit, offset, setLimit, setOffset } = usePagination<Plan>(
    (l, o) => api.plans.list({
      limit: l,
      offset: o,
      project: projectFilter || undefined,
      status: statusFilter === 'all' ? undefined : statusFilter,
    }),
    [projectFilter, statusFilter],
  );

  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    const timeout = setTimeout(() => {
      api.plans.search(searchQuery).then(setSearchResults);
    }, 300);
    return () => clearTimeout(timeout);
  }, [searchQuery]);

  const displayed = searchResults ?? items;

  if (loading && !searchResults) return <div className="loading">Loading...</div>;

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
        projectValue={projectFilter}
        onNameChange={setSearchQuery}
        onProjectChange={val => { setProjectFilter(val); setOffset(0); }}
        namePlaceholder="Search by title..."
      />

      {!searchResults && (
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
      )}

      <table className="table">
        <thead>
          <tr>
            <th>Title</th>
            <th>Status</th>
            <th>Project</th>
            <th>Last Updated</th>
          </tr>
        </thead>
        <tbody>
          {displayed.map(plan => (
            <tr
              key={plan.id}
              {...makeRowClickable(() => navigate(`/plans/${plan.id}`))}
              style={{ cursor: 'pointer' }}
            >
              <td>{plan.title}</td>
              <td>
                <span
                  className="tag"
                  style={plan.status === 'draft'
                    ? { color: 'var(--info, #3498db)', borderColor: 'var(--info, #3498db)' }
                    : undefined}
                >
                  {plan.status}
                </span>
              </td>
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
          {displayed.length === 0 && (
            <tr><td colSpan={4} className="loading">No plans found</td></tr>
          )}
        </tbody>
      </table>

      {!searchResults && (
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
