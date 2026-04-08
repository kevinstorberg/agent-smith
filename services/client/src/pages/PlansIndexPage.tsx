import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { Plan } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { DateCell } from '../components/table';
import { usePagination } from '../hooks/usePagination';
import { makeRowClickable } from '../utils/a11y';

export function PlansIndexPage() {
  const [projectFilter, setProjectFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Plan[] | null>(null);
  const navigate = useNavigate();

  const { items, total, loading, limit, offset, setLimit, setOffset } = usePagination<Plan>(
    (l, o) => api.plans.list({ limit: l, offset: o, project: projectFilter || undefined }),
    [projectFilter],
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
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Plans</h2>
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

      <table className="table">
        <thead>
          <tr>
            <th>Title</th>
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
            <tr><td colSpan={3} className="loading">No plans found</td></tr>
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
