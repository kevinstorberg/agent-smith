import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import { api } from '../api';
import type { AuditEvent } from '../api';
import { StatusBadge } from '../components/StatusBadge';
import { usePolling } from '../hooks/usePolling';
import { CODE_BOX } from '../components/codeBox';
import { formatDuration } from '../utils/audit';

const orDash = (value: string | null) =>
  value ?? <span style={{ color: 'var(--text-muted)' }}>—</span>;

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', gap: 8, padding: '4px 0' }}>
      <span style={{ minWidth: 130, color: 'var(--text-muted)' }}>{label}</span>
      <span>{children}</span>
    </div>
  );
}

function JsonPane({ title, value }: { title: string; value: unknown }) {
  return (
    <div style={{ flex: 1, minWidth: 280 }}>
      <div className="form-label">{title}</div>
      <pre style={CODE_BOX}>{JSON.stringify(value ?? null, null, 2)}</pre>
    </div>
  );
}

export function AuditDetailPage() {
  const { id } = useParams();
  const [event, setEvent] = useState<AuditEvent | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async ({ setErrorOnFailure = true }: { setErrorOnFailure?: boolean } = {}) => {
    try {
      setEvent(await api.audit.get(Number(id)));
      setError(null);
    } catch (err) {
      if (setErrorOnFailure) setError(err instanceof Error ? err.message : String(err));
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);
  usePolling(() => load({ setErrorOnFailure: false }), { enabled: Boolean(id) });

  if (error) return <div className="loading">Error: {error}</div>;
  if (!event) return <div className="loading">Loading...</div>;

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">
          {event.agent} · {event.tool_name}
        </h2>
        <Link className="btn" to="/audit">Back</Link>
      </div>

      <div className="card">
        <Row label="Status"><StatusBadge status={event.status} kind="audit" /></Row>
        <Row label="Agent">{event.agent}</Row>
        <Row label="Tool">{event.tool_name}</Row>
        <Row label="Session">{event.session_id}</Row>
        <Row label="Project">{orDash(event.project)}</Row>
        <Row label="Working dir">{orDash(event.cwd)}</Row>
        <Row label="Started">{event.created_at}</Row>
        <Row label="Completed">{orDash(event.completed_at)}</Row>
        <Row label="Duration">{formatDuration(event.duration_ms)}</Row>
        <Row label="Correlation"><code>{event.correlation_key}</code></Row>
      </div>

      <div className="card">
        <div className="section-title">Payload</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
          <JsonPane title="Tool input" value={event.tool_input} />
          {event.status !== 'pending' && <JsonPane title="Result" value={event.result} />}
        </div>
      </div>
    </div>
  );
}
