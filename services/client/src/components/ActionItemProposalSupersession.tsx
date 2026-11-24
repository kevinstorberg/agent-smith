import { Link } from 'react-router';
import type { ActionItemProposal } from '../api';

export function ActionItemProposalSupersession({
  proposal,
}: {
  proposal: ActionItemProposal;
}) {
  if (proposal.status !== 'superseded') return null;
  return (
    <p>
      Replaced by another Action Item proposal.{' '}
      {proposal.superseded_by_id === null ? (
        'Replacement unavailable.'
      ) : (
        <Link
          className="text-link"
          to={`/action-items/proposals/${proposal.superseded_by_id}`}
        >
          View replacement
        </Link>
      )}
    </p>
  );
}
