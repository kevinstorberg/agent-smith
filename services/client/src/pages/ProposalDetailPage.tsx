import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { api } from '../api';
import type { Proposal } from '../api';
import { useNotification } from '../context/useNotification';
import { StatusBadge } from '../components/StatusBadge';
import { usePolling } from '../hooks/usePolling';
import { usePageLifetime } from '../hooks/usePageLifetime';
import { ContentDiff } from '../components/ContentDiff';
import { CODE_BOX } from '../components/codeBox';
import { ActionItemProposalContent } from '../components/ActionItemProposalContent';

const JOB_FIELDS = ['schedule_config', 'input_params', 'description'] as const;

function bodyOf(item: Proposal['proposed_item']): string {
  return (item?.content as { body?: string } | undefined)?.body ?? '';
}

function jobFields(item: Proposal['proposed_item']): Record<string, unknown> {
  return Object.fromEntries(
    JOB_FIELDS.map((field) => [field, item?.[field] ?? null]),
  );
}

function Pane({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="operations-content-pane">
      <div className="form-label">{title}</div>
      <pre style={CODE_BOX}>{children}</pre>
    </div>
  );
}

export function ProposalDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isCurrent = usePageLifetime();
  const { notify } = useNotification();
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async ({
      setErrorOnFailure = true,
    }: { setErrorOnFailure?: boolean } = {}) => {
      try {
        setProposal(await api.proposals.get(Number(id)));
        setError(null);
      } catch (err) {
        if (setErrorOnFailure)
          setError(err instanceof Error ? err.message : String(err));
      }
    },
    [id],
  );

  useEffect(() => {
    load();
  }, [load]);
  usePolling(() => load({ setErrorOnFailure: false }), {
    enabled: Boolean(id) && !busy,
  });

  if (error) return <div className="loading">Error: {error}</div>;
  if (!proposal) return <div className="loading">Loading...</div>;

  const isJob = proposal.target_kind === 'job';
  const isActionItem = proposal.target_kind === 'action_item';
  const isUpdate = proposal.action === 'update';
  const targetMissing = isUpdate && !proposal.current_target;
  const targetStale =
    isActionItem &&
    proposal.status === 'pending' &&
    isUpdate &&
    !targetMissing &&
    proposal.current_target?.revision !== proposal.base_version;
  const sourceStale =
    isActionItem &&
    proposal.status === 'pending' &&
    (proposal.source_stale || proposal.source_available === false);
  const appliedActionItem = proposal.applied_ref?.action_item_id;

  async function review(action: 'approve' | 'reject') {
    setBusy(true);
    try {
      const updated = await api.proposals[action](Number(id));
      if (!isCurrent()) return;
      setProposal({ ...proposal, ...updated });
      notify(
        action === 'approve' ? 'Proposal applied' : 'Proposal rejected',
        'success',
      );
    } catch (err) {
      if (!isCurrent()) return;
      notify(
        `${action} failed: ${err instanceof Error ? err.message : String(err)}`,
        'error',
      );
      load();
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!confirm('Delete this proposal?')) return;
    setBusy(true);
    try {
      await api.proposals.remove(Number(id));
      if (isCurrent()) navigate('/proposals');
    } finally {
      setBusy(false);
    }
  }

  const before = isJob
    ? JSON.stringify(jobFields(proposal.current_target), null, 2)
    : bodyOf(proposal.current_target);
  const after = isJob
    ? JSON.stringify(jobFields(proposal.proposed_item), null, 2)
    : bodyOf(proposal.proposed_item);

  return (
    <div className="proposal-detail-page">
      <div className="page-header">
        <h2 className="page-title">{proposal.title}</h2>
        <div className="flex-wrap" style={{ gap: 8 }}>
          {proposal.status === 'pending' && (
            <>
              <button
                className="btn btn-primary"
                onClick={() => review('approve')}
                disabled={
                  busy || targetMissing || targetStale || Boolean(sourceStale)
                }
              >
                Approve
              </button>
              <button
                className="btn"
                onClick={() => review('reject')}
                disabled={busy}
              >
                Reject
              </button>
            </>
          )}
          <button
            className="btn sidebar-btn-danger"
            onClick={handleDelete}
            disabled={busy}
          >
            Delete
          </button>
        </div>
      </div>

      <div className="card">
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 8,
            alignItems: 'center',
          }}
        >
          <StatusBadge status={proposal.status} kind="proposal" />
          <span className="tag">
            {isActionItem ? 'Action item' : proposal.target_kind}
          </span>
          <span style={{ color: 'var(--text-muted)' }}>
            {isActionItem ? (isUpdate ? 'Update' : 'New') : proposal.action}{' '}
            <strong style={{ color: 'var(--text)' }}>
              {proposal.target_name}
            </strong>
            {proposal.base_version != null &&
              (isActionItem
                ? ` · from revision ${proposal.base_version}`
                : ` · from v${proposal.base_version}`)}
          </span>
          {proposal.project && (
            <span className="tag tag-project">{proposal.project}</span>
          )}
        </div>
        {targetMissing && (
          <p style={{ color: 'var(--danger, #e06c75)', margin: '12px 0 0' }}>
            The target of this proposal was deleted — it can no longer be
            applied.
          </p>
        )}
        {(targetStale || sourceStale) && (
          <p
            role="alert"
            style={{ color: 'var(--danger, #e06c75)', margin: '12px 0 0' }}
          >
            {sourceStale
              ? 'The source meeting changed or is unavailable.'
              : 'This action item changed after the proposal was generated.'}{' '}
            Generate a fresh proposal before approving; the reviewed changes
            below are preserved.
          </p>
        )}
        {typeof appliedActionItem === 'number' && (
          <p style={{ margin: '12px 0 0' }}>
            <Link
              className="text-link"
              to={`/action-items/${appliedActionItem}`}
            >
              Open saved action item
            </Link>
          </p>
        )}
      </div>

      <div className="card">
        <div className="section-title">Rationale</div>
        <p style={{ margin: 0, lineHeight: 1.7 }}>{proposal.rationale}</p>
      </div>

      {proposal.evidence.length > 0 && (
        <div className="card">
          <div className="section-title">Evidence</div>
          <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
            {proposal.evidence.map((entry, i) => (
              <li key={i}>
                {entry.source === 'meeting' ? (
                  <>
                    <Link
                      className="text-link"
                      to={`/meetings/${encodeURIComponent(entry.id)}`}
                    >
                      {entry.note || 'Meeting summary'}
                    </Link>
                    {entry.quote && (
                      <blockquote
                        style={{
                          whiteSpace: 'pre-wrap',
                          overflowWrap: 'anywhere',
                          margin: '8px 0 12px',
                          lineHeight: 1.6,
                        }}
                      >
                        {entry.quote}
                      </blockquote>
                    )}
                  </>
                ) : entry.source === 'plan' ? (
                  <Link to={`/plans/${entry.id}`}>plan {entry.id}</Link>
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}>
                    memory {entry.id}
                  </span>
                )}
                {entry.source !== 'meeting' && entry.note && (
                  <span style={{ color: 'var(--text-muted)' }}>
                    {' — '}
                    {entry.note}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card">
        <div className="section-title">
          {isUpdate ? 'Change' : 'Proposed content'}
        </div>
        {isActionItem ? (
          <ActionItemProposalContent
            proposal={proposal}
            targetStale={targetStale}
          />
        ) : isUpdate ? (
          <ContentDiff before={before} after={after} />
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
            <Pane title="Proposed">{after}</Pane>
          </div>
        )}
      </div>
    </div>
  );
}
