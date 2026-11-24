import type { ActionItemProposal } from '../../api';
import { actionItem } from './actionItemFixture';

export function actionItemProposal(
  overrides: Partial<ActionItemProposal> = {},
): ActionItemProposal {
  const before = actionItem(12, {
    title: 'Send the release report',
    description: 'Send the report to the team.',
    project: 'Work',
    due_at: '2026-11-18T17:00:00Z',
    revision: 3,
  });
  return {
    id: 1,
    action: 'update',
    target_name: before.title,
    project: before.project,
    target_id: before.id,
    base_version: before.revision,
    title: 'Update: Send the release report',
    rationale: 'The meeting agreed to move the deadline.',
    evidence: [
      {
        source: 'meeting',
        id: 'meeting-123',
        note: 'Release planning',
        quote: 'Move the release report deadline to Friday at 5 PM UTC.',
        revision: 2,
      },
    ],
    status: 'pending',
    superseded_by_id: null,
    applied_ref: null,
    created_at: '2026-11-17T12:00:00Z',
    updated_at: '2026-11-17T12:00:00Z',
    proposed_item: { ...before, due_at: '2026-11-20T17:00:00Z' },
    current_target: before,
    before_snapshot: before,
    source_stale: false,
    source_available: true,
    ...overrides,
  };
}
