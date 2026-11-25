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
