import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { AuditEvent, AuditCounts } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { StatusBadge } from '../components/StatusBadge';
import { ScrollableTable } from '../components/ScrollableTable';
import { DateCell, ProjectCell } from '../components/table';
import { usePagination } from '../hooks/usePagination';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { formatDuration } from '../utils/audit';
import { ALL_AGENTS, AUDIT_SORT_OPTIONS, AUDIT_STATUSES } from '../constants';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { parseViewField } from '../utils/viewPreferences';

export function AuditIndexPage() {
  const preferences = useViewPreferences('audit');
  const { agent, status, q: query, project, sort } = preferences.values;
  const debouncedQuery = useDebouncedValue(query);
  const debouncedProject = useDebouncedValue(project);
  const [counts, setCounts] = useState<AuditCounts | null>(null);
  const navigate = useNavigate();

  const { items, total, loading, error, limit, offset, setLimit, setOffset, refresh } = usePagination<AuditEvent>(
    (l, o) => api.audit.list({ agent: agent || undefined, status: status || undefined,
      q: debouncedQuery || undefined, project: debouncedProject || undefined, sort }, { limit: l, offset: o }),
    [agent, status, debouncedQuery, debouncedProject, sort],
    10, { ...preferences.pagination, enabled: debouncedQuery === query && debouncedProject === project },
  );
  const loadCounts = useCallback(async () => {
    try {
      setCounts(await api.audit.counts());
    } catch {
      setCounts(null);
    }
  }, []);

  useEffect(() => {
    loadCounts();
  }, [loadCounts]);
  usePolling(async () => {
    await Promise.all([
      refresh({ showLoading: false }),
      loadCounts(),
    ]);
  });

  const showCounts = !query && !debouncedQuery && !project && !debouncedProject && !status;

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Audit Trail</h2>
      </div>

      <FilterBar nameValue={query} onNameChange={value => preferences.setField('q', value)} namePlaceholder="Search audit events..."
        projectValue={project} onProjectChange={value => preferences.setField('project', value)} onReset={preferences.reset}>
        <label><span className="form-label">Sort audit events</span>
        <select aria-label="Sort audit events" value={sort} onChange={event => preferences.setField('sort', parseViewField('audit', 'sort', event.target.value))}>
          {AUDIT_SORT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        </label>
      </FilterBar>
      <div className="filters">
        <button
          className={`btn${agent === '' ? ' btn-primary' : ''}`}
          onClick={() => preferences.setField('agent', '')}
        >
          all agents
        </button>
        {ALL_AGENTS.map(a => (
          <button
            key={a}
            className={`btn${agent === a ? ' btn-primary' : ''}`}
            onClick={() => preferences.setField('agent', a)}
          >
            {a}{showCounts && counts ? ` (${counts[a]})` : ''}
          </button>
        ))}
      </div>

      <div className="filters">
        <button
          className={`btn${status === '' ? ' btn-primary' : ''}`}
          onClick={() => preferences.setField('status', '')}
        >
          any status
        </button>
        {AUDIT_STATUSES.map(s => (
          <button
            key={s}
            className={`btn${status === s ? ' btn-primary' : ''}`}
            onClick={() => preferences.setField('status', s)}
          >
            {s}
          </button>
        ))}
      </div>

      {error && <p role="alert">Could not load audit events. <button className="btn btn-sm" onClick={() => refresh()}>Retry</button></p>}
      {loading && <div className="loading" role="status">Loading...</div>}
      <ScrollableTable label="Audit events" className="audit-list-table" empty={items.length === 0}>
        <thead>
          <tr>
            <th>Time</th>
            <th>Agent</th>
            <th>Tool</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Project</th>
          </tr>
        </thead>
        <tbody>
          {!loading && !error && items.map(event => (
            <tr
              key={event.id}
              {...makeRowClickable(() => navigate(`/audit/${event.id}`))}
              style={{ cursor: 'pointer' }}
            >
              <td><DateCell date={event.created_at} /></td>
              <td><span className="tag">{event.agent}</span></td>
              <td>{event.tool_name}</td>
              <td><StatusBadge status={event.status} kind="audit" /></td>
              <td>{formatDuration(event.duration_ms)}</td>
              <td><ProjectCell project={event.project} /></td>
            </tr>
          ))}
          {!loading && !error && items.length === 0 && (
            <tr><td colSpan={6} className="loading">No tool-call events</td></tr>
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
