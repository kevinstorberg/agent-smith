import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { AuditEvent, AuditCounts } from '../api';
import { Pagination } from '../components/Pagination';
import { StatusBadge } from '../components/StatusBadge';
import { DateCell, ProjectCell } from '../components/table';
import { usePagination } from '../hooks/usePagination';
import { makeRowClickable } from '../utils/a11y';
import { formatDuration } from '../utils/audit';

const AGENTS = ['claude', 'codex', 'gemini'] as const;
const STATUSES = ['pending', 'success', 'error'] as const;

export function AuditIndexPage() {
  const [agent, setAgent] = useState<string>('');
  const [status, setStatus] = useState<string>('');
  const [counts, setCounts] = useState<AuditCounts | null>(null);
  const navigate = useNavigate();

  const { items, total, loading, limit, offset, setLimit, setOffset } = usePagination<AuditEvent>(
    (l, o) => api.audit.list({ agent: agent || undefined, status: status || undefined }, { limit: l, offset: o }),
    [agent, status],
  );

  useEffect(() => {
    api.audit.counts().then(setCounts).catch(() => setCounts(null));
  }, [items]);

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Audit Trail</h2>
      </div>

      <div className="filters">
        <button
          className={`btn${agent === '' ? ' btn-primary' : ''}`}
          onClick={() => { setAgent(''); setOffset(0); }}
        >
          all agents
        </button>
        {AGENTS.map(a => (
          <button
            key={a}
            className={`btn${agent === a ? ' btn-primary' : ''}`}
            onClick={() => { setAgent(a); setOffset(0); }}
          >
            {a}{counts ? ` (${counts[a]})` : ''}
          </button>
        ))}
      </div>

      <div className="filters">
        <button
          className={`btn${status === '' ? ' btn-primary' : ''}`}
          onClick={() => { setStatus(''); setOffset(0); }}
        >
          any status
        </button>
        {STATUSES.map(s => (
          <button
            key={s}
            className={`btn${status === s ? ' btn-primary' : ''}`}
            onClick={() => { setStatus(s); setOffset(0); }}
          >
            {s}
          </button>
        ))}
      </div>

      <table className="table">
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
          {items.map(event => (
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
          {items.length === 0 && (
            <tr><td colSpan={6} className="loading">No tool-call events</td></tr>
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
