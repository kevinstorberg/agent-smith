import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { api } from '../api';
import type { AuditEvent, AuditCounts } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { StatusBadge } from '../components/StatusBadge';
import { ScrollableTable } from '../components/ScrollableTable';
import { DateCell, ProjectCell } from '../components/table';
import { SortableHeader } from '../components/table/SortableHeader';
import { usePagination } from '../hooks/usePagination';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { formatDuration } from '../utils/audit';
import { ALL_AGENTS, AUDIT_SORT_COLUMNS, AUDIT_STATUSES } from '../constants';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { parseViewField } from '../utils/viewPreferences';
import './auditSorting.css';

export function AuditIndexPage() {
  const preferences = useViewPreferences('audit');
  const { agent, status, q: query, project, sort } = preferences.values;
  const debouncedQuery = useDebouncedValue(query);
  const debouncedProject = useDebouncedValue(project);
  const [counts, setCounts] = useState<AuditCounts | null>(null);
  const navigate = useNavigate();

  const {
    items,
    total,
    loading,
    error,
    dataCurrent,
    limit,
    offset,
    setLimit,
    setOffset,
    refresh,
  } = usePagination<AuditEvent>(
    (l, o) =>
      api.audit.list(
        {
          agent: agent || undefined,
          status: status || undefined,
          q: debouncedQuery || undefined,
          project: debouncedProject || undefined,
          sort,
        },
        { limit: l, offset: o },
      ),
    [agent, status, debouncedQuery, debouncedProject, sort],
    10,
    {
      ...preferences.pagination,
      enabled: debouncedQuery === query && debouncedProject === project,
    },
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
    await Promise.all([refresh({ showLoading: false }), loadCounts()]);
  });

  const showCounts =
    !query && !debouncedQuery && !project && !debouncedProject && !status;
  const hasFilters = Boolean(query || project || agent || status);
  const updating =
    loading ||
    (!error && !dataCurrent) ||
    query !== debouncedQuery ||
    project !== debouncedProject;
  const accepted = !error && !updating;

  return (
    <div className="audit-page">
      <div className="page-header">
        <h2 className="page-title">Audit Trail</h2>
      </div>

      <FilterBar
        className="audit-toolbar"
        nameValue={query}
        onNameChange={(value) => preferences.setField('q', value)}
        namePlaceholder="Search audit events..."
        projectLabel="Project"
        projectValue={project}
        onProjectChange={(value) => preferences.setField('project', value)}
      >
        <label className="audit-agent-filter">
          <span className="form-label">Agent</span>
          <select
            value={agent}
            onChange={(event) =>
              preferences.setField(
                'agent',
                parseViewField('audit', 'agent', event.target.value),
              )
            }
          >
            <option value="">All agents</option>
            {ALL_AGENTS.map((option) => (
              <option key={option} value={option}>
                {option}
                {showCounts && counts ? ` (${counts[option]})` : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="audit-status-filter">
          <span className="form-label">Status</span>
          <select
            value={status}
            onChange={(event) =>
              preferences.setField(
                'status',
                parseViewField('audit', 'status', event.target.value),
              )
            }
          >
            <option value="">Any status</option>
            {AUDIT_STATUSES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
      </FilterBar>

      <div className="audit-results-summary" role="status">
        {updating
          ? 'Updating…'
          : !error &&
            `${total.toLocaleString()} ${hasFilters ? 'matching ' : ''}tool call${total === 1 ? '' : 's'}`}
      </div>
      <div className="audit-results" aria-busy={updating}>
        {error && (
          <p role="alert">
            Could not load audit events.{' '}
            <button
              className="btn btn-sm"
              disabled={updating}
              onClick={() => refresh()}
            >
              Retry
            </button>
          </p>
        )}
        <ScrollableTable
          label="Audit events"
          className="audit-list-table"
          busy={updating && (loading || !error)}
          emptyState={
            accepted &&
            items.length === 0 && (
              <section className="audit-empty">
                <h3>
                  {hasFilters ? 'No matching tool calls' : 'No tool calls yet'}
                </h3>
                <p>
                  {hasFilters
                    ? 'Try a different search or reset this view.'
                    : 'Activity will appear here when an agent runs a tool.'}
                </p>
              </section>
            )
          }
        >
          <thead>
            <tr>
              {(
                [
                  ['Tool', 'tool'],
                  ['Status', 'status'],
                  ['Agent', 'agent'],
                  ['Duration', 'duration'],
                  ['Project', 'project'],
                  ['Time', 'time'],
                ] as const
              ).map(([label, key]) => (
                <SortableHeader
                  key={key}
                  sort={sort}
                  column={AUDIT_SORT_COLUMNS[key]}
                  current={accepted}
                  onSort={(value) => preferences.setField('sort', value)}
                >
                  {label}
                </SortableHeader>
              ))}
            </tr>
          </thead>
          <tbody>
            {accepted &&
              items.map((event) => (
                <tr
                  key={event.id}
                  {...makeRowClickable(() => navigate(`/audit/${event.id}`))}
                  style={{ cursor: 'pointer' }}
                >
                  <td>
                    <Link
                      className="audit-tool-link"
                      to={`/audit/${event.id}`}
                      onClick={(event) => event.stopPropagation()}
                    >
                      {event.tool_name}
                    </Link>
                  </td>
                  <td>
                    <StatusBadge status={event.status} kind="audit" />
                  </td>
                  <td>{event.agent}</td>
                  <td className="audit-duration">
                    {formatDuration(event.duration_ms)}
                  </td>
                  <td>
                    <ProjectCell project={event.project} />
                  </td>
                  <td className="audit-time">
                    <DateCell date={event.created_at} />
                  </td>
                </tr>
              ))}
          </tbody>
        </ScrollableTable>
      </div>

      {accepted && (
        <Pagination
          total={total}
          limit={limit}
          offset={offset}
          onPageChange={setOffset}
          onLimitChange={(newLimit) => {
            setLimit(newLimit);
            setOffset(0);
          }}
          disabled={loading}
        />
      )}
    </div>
  );
}
