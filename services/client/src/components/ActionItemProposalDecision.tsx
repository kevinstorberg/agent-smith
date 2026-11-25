import { useState } from 'react';
import type {
  ActionItemEpic,
  ActionItemEpicReference,
  ActionItemProposal,
  ActionItemProposalPlacement,
} from '../api';
import { epicOptionLabel, epicReference } from '../utils/actionItemEpics';
import { ActionItemEpicSelect } from './ActionItemEpicSelect';
import './actionItemProposalPlacement.css';

export interface ProposalEpicCatalog {
  data: { items: ActionItemEpic[] } | null;
  loading: boolean;
  error: string | null;
}

function sameReference(
  first: ActionItemEpicReference | null,
  second: ActionItemEpicReference | null,
) {
  return first === null || second === null
    ? first === second
    : first.id === second.id &&
        first.expected_revision === second.expected_revision &&
        first.cohort === second.cohort;
}

export function ActionItemProposalEpicCatalogStatus({
  catalog,
  busy,
  onRefresh,
}: {
  catalog: ProposalEpicCatalog;
  busy: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="action-item-proposal-epic-status">
      {catalog.loading && <span role="status">Loading Epics…</span>}
      {catalog.error && (
        <span role="alert">
          Could not load Epics. You can still accept without changing the Epic.
        </span>
      )}
      <button
        type="button"
        className="inline-clear"
        disabled={busy || catalog.loading}
        onClick={onRefresh}
      >
        {catalog.error ? 'Retry Epics' : 'Refresh Epics'}
      </button>
    </div>
  );
}

export function ActionItemProposalDecision({
  proposal,
  catalog,
  busy,
  saving,
  approveDisabled,
  approveLabel = 'Accept',
  onDecide,
}: {
  proposal: ActionItemProposal;
  catalog: ProposalEpicCatalog;
  busy: boolean;
  saving: boolean;
  approveDisabled: boolean;
  approveLabel?: string;
  onDecide: (
    action: 'approve' | 'reject',
    placement?: ActionItemProposalPlacement,
  ) => void;
}) {
  const [selection, setSelection] = useState<{
    label: string;
    placement: ActionItemProposalPlacement;
  } | null>(null);
  const epics = catalog.data?.items ?? [];
  const parentKnown =
    proposal.action === 'create' || proposal.current_parent !== undefined;
  const currentParent =
    proposal.action === 'create' ? null : (proposal.current_parent ?? null);
  const destination =
    selection &&
    epics.find((epic) => epic.id === selection.placement.destination.id);
  const earlier = Boolean(
    selection &&
    (!destination ||
      !sameReference(
        selection.placement.destination,
        epicReference(destination),
      ) ||
      !parentKnown ||
      !sameReference(selection.placement.expected_parent, currentParent)),
  );
  return (
    <div className="action-item-proposal-decision-controls">
      <div className="action-item-proposal-epic-choice">
        <ActionItemEpicSelect
          label="Epic"
          ariaLabel={`Epic for ${proposal.target_name}`}
          value={
            selection
              ? earlier
                ? 'earlier'
                : String(selection.placement.destination.id)
              : ''
          }
          defaultLabel={
            proposal.action === 'create' ? 'No Epic' : 'Keep current Epic'
          }
          epics={epics}
          disabled={busy || !parentKnown}
          retainedOption={
            earlier && selection
              ? {
                  value: 'earlier',
                  label: `${selection.label} — earlier choice`,
                }
              : undefined
          }
          onChange={(value) => {
            if (busy || !parentKnown || value === 'earlier') return;
            if (!value) {
              setSelection(null);
              return;
            }
            const epic = epics.find((item) => String(item.id) === value);
            if (!epic) return;
            setSelection({
              label: epicOptionLabel(epic, epics),
              placement: {
                expected_parent: currentParent ? { ...currentParent } : null,
                destination: epicReference(epic),
              },
            });
          }}
        />
        {earlier && (
          <span className="text-muted-sm">
            Earlier Epic details are kept for retry. Choose again to use current
            details.
          </span>
        )}
        {!parentKnown && (
          <span className="text-muted-sm">
            Refresh the proposal before choosing an Epic.
          </span>
        )}
      </div>
      <div className="action-item-proposal-decision-buttons">
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || approveDisabled}
          onClick={() => {
            if (!busy && !approveDisabled)
              onDecide('approve', selection?.placement);
          }}
        >
          {saving ? 'Saving…' : approveLabel}
        </button>
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={() => {
            if (!busy) onDecide('reject');
          }}
        >
          Reject
        </button>
      </div>
    </div>
  );
}
