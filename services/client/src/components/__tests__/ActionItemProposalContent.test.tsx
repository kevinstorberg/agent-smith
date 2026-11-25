import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { ActionItemProposalContent } from '../ActionItemProposalContent';
import { actionItemProposal } from '../../pages/__tests__/actionItemProposalFixture';

function change(field: string, before: unknown, after: unknown) {
  const proposal = actionItemProposal();
  const snapshot = { ...proposal.before_snapshot, [field]: before };
  return {
    ...proposal,
    before_snapshot: snapshot,
    current_target: snapshot,
    proposed_item: { ...snapshot, [field]: after },
  };
}

describe('reviewed proposal field values', () => {
  const emptyFields = [
    ['description', 'Description', ''],
    ['project', 'Project', ''],
    ['due_at', 'Deadline', ''],
    ['tags', 'Tags', []],
  ] as const;
  for (const [field, label, empty] of emptyFields) {
    it.each([undefined, null, empty])(
      `does not invent a ${label} change from an equivalent empty value (%j)`,
      (before) => {
        render(
          <ActionItemProposalContent
            proposal={change(field, before, empty)}
            targetStale={false}
          />,
        );
        expect(screen.queryByRole('rowheader', { name: label })).toBeNull();
      },
    );
  }

  it('preserves the reviewed description when the live task differs', () => {
    const proposal = change(
      'description',
      'Reviewed description',
      'Proposed description',
    );
    proposal.current_target = {
      ...proposal.current_target,
      description: 'Later saved description',
    };
    render(<ActionItemProposalContent proposal={proposal} targetStale />);
    const reviewed = screen.getByRole('region', {
      name: 'Proposed action item changes',
    });
    expect(within(reviewed).getByText('Reviewed description')).toBeVisible();
    expect(within(reviewed).getByText('Proposed description')).toBeVisible();
    expect(within(reviewed).queryByText('Later saved description')).toBeNull();
  });

  it.each([
    [
      'description',
      'Description',
      'Remove this description',
      '',
      'No description',
    ],
    ['project', 'Project', 'Previous project', '', 'No project'],
    ['tags', 'Tags', ['old-tag'], [], 'No tags'],
    ['due_at', 'Deadline', '2026-11-18T17:00:00Z', null, 'No deadline'],
  ])(
    'retains both cells for a cleared %s',
    (field, label, before, after, emptyValue) => {
      render(
        <ActionItemProposalContent
          proposal={change(field as string, before, after)}
          targetStale={false}
        />,
      );
      const row = screen
        .getByRole('rowheader', { name: label as string })
        .closest('tr')!;
      const cells = within(row).getAllByRole('cell');
      expect(cells).toHaveLength(2);
      expect(cells[0]).not.toHaveTextContent('None');
      expect(cells[1]).toHaveTextContent(emptyValue as string);
    },
  );
});
