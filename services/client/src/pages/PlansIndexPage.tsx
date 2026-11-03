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
import { useViewPreferences } from '../hooks/useViewPreferences';
import { PLAN_SORT_OPTIONS, PLAN_STATUSES, parseViewField } from '../utils/viewPreferences';

export function PlansIndexPage() {
  const preferences = useViewPreferences('plans');
  const { project: projectInput, status: statusFilter, q: searchQuery, sort } = preferences.values;
  const projectFilter = useDebouncedValue(projectInput.trim());
  const debouncedSearch = useDebouncedValue(searchQuery.trim());
  const searchTerm = searchQuery.trim() ? debouncedSearch : '';
  const navigate = useNavigate();

  const { items, total, loading, error, limit, offset, setLimit, setOffset, refresh } = usePagination<Plan>(
    (limit, offset) => api.plans.list({ limit, offset, q: searchTerm || undefined,
      project: projectFilter || undefined, status: statusFilter === 'all' ? undefined : statusFilter, sort }),
    [searchTerm, projectFilter, statusFilter, sort],
    10, { ...preferences.pagination, enabled: projectFilter === projectInput.trim() && debouncedSearch === searchQuery.trim() },
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
        onNameChange={value => preferences.setField('q', value)}
        onProjectChange={value => preferences.setField('project', value)}
        nameLabel="Search plans"
        namePlaceholder="Search by title..."
        onReset={preferences.reset}
      >
        <label><span className="form-label">Sort plans</span>
          <select className="input" value={sort} onChange={event => preferences.setField('sort', parseViewField('plans', 'sort', event.target.value))}>
            {PLAN_SORT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
      </FilterBar>

      <div className="filters">
          {PLAN_STATUSES.map(status => (
            <button
              key={status}
              className={`btn${statusFilter === status ? ' btn-primary' : ''}`}
              onClick={() => preferences.setField('status', status)}
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
