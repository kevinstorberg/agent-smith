import type { ReactNode } from 'react';
import type { ActionItemProposal } from '../api';
import { actionItemProposalProject } from '../utils/actionItems';
import { ActionItemProposalDescriptionPreview } from './ActionItemProposalContent';
import { ActionItemTitleText, ActionItemTopics } from './ActionItemTaskSummary';
import { DateCell } from './table';

export function ActionItemProposalSummary({
  proposal,
  title,
  titleId,
  showStatus = false,
}: {
  proposal: ActionItemProposal;
  title: ReactNode;
  titleId?: string;
  showStatus?: boolean;
}) {
  const isCreate = proposal.action === 'create';
  const item = proposal.proposed_item;
  const project = actionItemProposalProject(proposal);
  return (
    <div className="action-item-proposal-heading action-item-proposal-summary">
      <div className="action-item-proposal-identity">
        <h3 id={titleId}>
          <ActionItemTitleText>{title}</ActionItemTitleText>
        </h3>
        <div className="action-item-proposal-metadata">
          <span>
            {isCreate ? 'New action item' : 'Update existing action item'}
          </span>
          {isCreate && item?.status && item.status !== 'open' && (
            <span>Creates {item.status} item</span>
          )}
          {showStatus && <span>{proposal.status}</span>}
        </div>
        {isCreate && (
          <ActionItemProposalDescriptionPreview
            description={item?.description}
          />
        )}
      </div>
      <div className="action-item-proposal-topics">
        <span className="action-item-proposal-field-label">Project / Tags</span>
        <ActionItemTopics
          item={{ project: project ?? null, tags: item?.tags ?? [] }}
          quiet
        />
      </div>
      <div className="action-item-proposal-due">
        <span className="action-item-proposal-field-label">Due</span>
        {item?.due_at ? (
          <DateCell date={item.due_at} format="long" />
        ) : (
          <span className="text-muted">
            —<span className="visually-hidden">No deadline</span>
          </span>
        )}
      </div>
    </div>
  );
}
