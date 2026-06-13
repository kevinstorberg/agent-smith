import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { api } from '../api';
import type { Proposal } from '../api';
import { useNotification } from '../context/useNotification';

const JOB_FIELDS = ['schedule_config', 'input_params', 'description'] as const;

function bodyOf(item: Proposal['proposed_item']): string {
  return (item?.content as { body?: string } | undefined)?.body ?? '';
}

function jobFields(item: Proposal['proposed_item']): Record<string, unknown> {
  return Object.fromEntries(JOB_FIELDS.map(field => [field, item?.[field] ?? null]));
}

function Pane({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <h4 style={{ margin: '0 0 8px' }}>{title}</h4>
      <pre
        style={{
          whiteSpace: 'pre-wrap',
          overflowWrap: 'anywhere',
          background: 'var(--bg-secondary, #f6f6f6)',
          padding: 12,
          borderRadius: 6,
          maxHeight: 480,
          overflow: 'auto',
        }}
      >
        {children}
      </pre>
    </div>
  );
}

export function ProposalDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { notify } = useNotification();
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.proposals
      .get(Number(id))
      .then(setProposal)
      .catch(err => setError(err instanceof Error ? err.message : String(err)));
  }, [id]);

  useEffect(load, [load]);

  if (error) return <div className="loading">Error: {error}</div>;
  if (!proposal) return <div className="loading">Loading...</div>;

  const isJob = proposal.target_kind === 'job';
  const isUpdate = proposal.action === 'update';
  const targetMissing = isUpdate && !proposal.current_target;

  async function review(action: 'approve' | 'reject') {
    setBusy(true);
    try {
      const updated = await api.proposals[action](Number(id));
      setProposal({ ...proposal, ...updated });
      notify(action === 'approve' ? 'Proposal applied' : 'Proposal rejected', 'success');
    } catch (err) {
      notify(`${action} failed: ${err instanceof Error ? err.message : String(err)}`, 'error');
      load();
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!confirm('Delete this proposal?')) return;
    await api.proposals.remove(Number(id));
    navigate('/proposals');
  }

  const before = isJob
    ? JSON.stringify(jobFields(proposal.current_target), null, 2)
    : bodyOf(proposal.current_target);
  const after = isJob
    ? JSON.stringify(jobFields(proposal.proposed_item), null, 2)
    : bodyOf(proposal.proposed_item);

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">{proposal.title}</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {proposal.status === 'pending' && (
            <>
              <button
                className="btn btn-primary"
                onClick={() => review('approve')}
                disabled={busy || targetMissing}
              >
                Approve
              </button>
              <button className="btn" onClick={() => review('reject')} disabled={busy}>
                Reject
              </button>
            </>
          )}
          <button className="btn sidebar-btn-danger" onClick={handleDelete} disabled={busy}>
            Delete
          </button>
        </div>
      </div>

      <p>
        <span className="tag">{proposal.status}</span>{' '}
        <span className="tag">{proposal.target_kind}</span>{' '}
        {proposal.action} <strong>{proposal.target_name}</strong>
        {proposal.project && <span className="tag tag-project">{proposal.project}</span>}
        {proposal.base_version != null && ` (from v${proposal.base_version})`}
      </p>

      {targetMissing && (
        <p style={{ color: 'var(--danger, #c0392b)' }}>
          The target of this proposal was deleted — it can no longer be applied.
        </p>
      )}

      <h3>Rationale</h3>
      <p>{proposal.rationale}</p>

      {proposal.evidence.length > 0 && (
        <>
          <h3>Evidence</h3>
          <ul>
            {proposal.evidence.map((entry, i) => (
              <li key={i}>
                {entry.source === 'plan' ? (
                  <Link to={`/plans/${entry.id}`}>plan {entry.id}</Link>
                ) : (
                  <span>memory {entry.id}</span>
                )}
                {entry.note && ` — ${entry.note}`}
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>{isUpdate ? 'Change' : 'Proposed content'}</h3>
      <div style={{ display: 'flex', gap: 16 }}>
        {isUpdate && <Pane title="Current">{before}</Pane>}
        <Pane title="Proposed">{after}</Pane>
      </div>
    </div>
  );
}
