import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
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

export function AuditIndexPage() {
  const [agent, setAgent] = useState<string>('');
  const [status, setStatus] = useState<string>('');
  const [query, setQuery] = useState('');
  const [project, setProject] = useState('');
  const [sort, setSort] = useState<typeof AUDIT_SORT_OPTIONS[number]['value']>('newest');
  const debouncedQuery = useDebouncedValue(query);
  const debouncedProject = useDebouncedValue(project);
  const [counts, setCounts] = useState<AuditCounts | null>(null);
  const navigate = useNavigate();

  const { items, total, loading, error, dataCurrent, limit, offset, setLimit, setOffset, refresh } = usePagination<AuditEvent>(
    (l, o) => api.audit.list({ agent: agent || undefined, status: status || undefined,
      q: debouncedQuery || undefined, project: debouncedProject || undefined, sort }, { limit: l, offset: o }),
    [agent, status, debouncedQuery, debouncedProject, sort],
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
  const hasFilters = Boolean(query || project || agent || status);
  const updating = loading || (!error && !dataCurrent) || query !== debouncedQuery || project !== debouncedProject;
  const accepted = !error && !updating;
  const resetView = () => {
    setQuery(''); setProject(''); setAgent(''); setStatus(''); setSort('newest'); setLimit(10); setOffset(0);
  };

  return (
    <div className="audit-page">
      <div className="page-header">
        <h2 className="page-title">Audit Trail</h2>
      </div>

      <FilterBar className="audit-toolbar" nameValue={query} onNameChange={setQuery} namePlaceholder="Search audit events..."
        projectLabel="Project" projectValue={project} onProjectChange={setProject} onReset={resetView}>
        <label className="audit-agent-filter"><span className="form-label">Agent</span>
          <select value={agent} onChange={event => {
            const value = event.target.value;
            if (value === '' || ALL_AGENTS.some(option => option === value)) { setAgent(value); setOffset(0); }
          }}>
            <option value="">All agents</option>
            {ALL_AGENTS.map(option => <option key={option} value={option}>{option}{showCounts && counts ? ` (${counts[option]})` : ''}</option>)}
          </select>
        </label>
        <label className="audit-status-filter"><span className="form-label">Status</span>
          <select value={status} onChange={event => {
            const value = event.target.value;
            if (value === '' || AUDIT_STATUSES.some(option => option === value)) { setStatus(value); setOffset(0); }
          }}>
            <option value="">Any status</option>
            {AUDIT_STATUSES.map(option => <option key={option} value={option}>{option}</option>)}
          </select>
        </label>
        <label className="audit-sort-filter"><span className="form-label">Sort</span>
          <select value={sort} onChange={event => {
            const option = AUDIT_SORT_OPTIONS.find(option => option.value === event.target.value);
            if (option) setSort(option.value);
          }}>
            {AUDIT_SORT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
      </FilterBar>

      <div className="audit-results-summary" role="status">
        {updating ? 'Updating…' : !error && `${total.toLocaleString()} ${hasFilters ? 'matching ' : ''}tool call${total === 1 ? '' : 's'}`}
      </div>
      <div className="audit-results" aria-busy={updating}>
      {error && <p role="alert">Could not load audit events. <button className="btn btn-sm" disabled={updating} onClick={() => refresh()}>Retry</button></p>}
      {accepted && items.length === 0 && <section className="audit-empty" role="region" aria-label="Audit events">
        <h3>{hasFilters ? 'No matching tool calls' : 'No tool calls yet'}</h3>
        <p>{hasFilters ? 'Try a different search or reset this view.' : 'Activity will appear here when an agent runs a tool.'}</p>
      </section>}
      {accepted && items.length > 0 && <ScrollableTable label="Audit events" className="audit-list-table">
        <thead>
          <tr>
            <th>Tool</th>
            <th>Status</th>
            <th>Agent</th>
            <th aria-sort={sort === 'duration' ? 'descending' : undefined}>Duration</th>
            <th>Project</th>
            <th aria-sort={sort === 'newest' ? 'descending' : sort === 'oldest' ? 'ascending' : undefined}>Time</th>
          </tr>
        </thead>
        <tbody>
          {items.map(event => (
            <tr
              key={event.id}
              {...makeRowClickable(() => navigate(`/audit/${event.id}`))}
              style={{ cursor: 'pointer' }}
            >
              <td><Link className="audit-tool-link" to={`/audit/${event.id}`} onClick={event => event.stopPropagation()}>{event.tool_name}</Link></td>
              <td><StatusBadge status={event.status} kind="audit" /></td>
              <td>{event.agent}</td>
              <td className="audit-duration">{formatDuration(event.duration_ms)}</td>
              <td><ProjectCell project={event.project} /></td>
              <td className="audit-time"><DateCell date={event.created_at} /></td>
            </tr>
          ))}
        </tbody>
      </ScrollableTable>}
      </div>

      {accepted && <Pagination
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
