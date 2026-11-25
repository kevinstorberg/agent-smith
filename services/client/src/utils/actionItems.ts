import type { ActionItemProposal } from '../api';

export function actionItemTags(value: string): string[] {
  return value
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
}

export function actionItemProposalProject(proposal: ActionItemProposal) {
  return proposal.action === 'create'
    ? proposal.proposed_item?.project
    : proposal.project;
}

export function actionItemProposalDecisionMessage(
  proposal: ActionItemProposal,
) {
  return proposal.review_outcome === 'completed'
    ? 'Action Item accepted as done'
    : proposal.status === 'approved'
      ? 'Action Item accepted'
      : 'Action Item rejected';
}
