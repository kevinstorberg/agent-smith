import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { Plan } from '../api';
import { Pagination } from '../components/Pagination';
import { usePagination } from '../hooks/usePagination';

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

      <div className="filters" style={{ marginBottom: 12 }}>
        <input
          placeholder="Search by title..."
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          style={{ maxWidth: 260 }}
        />
        <input
          placeholder="Filter by project..."
          value={projectFilter}
          onChange={e => { setProjectFilter(e.target.value); setOffset(0); }}
          style={{ maxWidth: 220 }}
        />
      </div>

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
              onClick={() => navigate(`/plans/${plan.id}`)}
              style={{ cursor: 'pointer' }}
            >
              <td>{plan.title}</td>
              <td>
                {plan.project
                  ? <span className="tag tag-project">{plan.project}</span>
                  : <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>--</span>
                }
              </td>
              <td style={{ color: 'var(--text-muted)', fontSize: 13 }}>
                {new Date(plan.updated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </td>
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
