import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ActionItemProposalDecision } from '../ActionItemProposalDecision';
import { actionItemProposal } from '../../pages/__tests__/actionItemProposalFixture';
import { epicGroup } from '../../pages/__tests__/actionItemEpicFixture';
import { epicReference } from '../../utils/actionItemEpics';
import { chooseEpic } from '../../test-utils/epicPicker';

beforeEach(() => vi.spyOn(window, 'confirm').mockReturnValue(true));
afterEach(() => vi.restoreAllMocks());

const proposal = actionItemProposal();
const props = () => ({
  proposal,
  catalog: { data: { items: [] }, loading: false, error: null },
  busy: false,
  saving: false,
  approveDisabled: false,
  onDecide: vi.fn(),
});

describe('completing a proposed Action Item', () => {
  it.each(['create', 'update'] as const)(
    'confirms accepting a %s as completed with the shared icon control',
    (action) => {
      const input = props();
      render(
        <ActionItemProposalDecision
          {...input}
          proposal={{ ...proposal, action }}
        />,
      );
      const complete = screen.getByRole('button', {
        name: `Complete ${proposal.target_name}`,
      });
      expect(complete.querySelector('svg')).not.toBeNull();
      fireEvent.click(complete);
      expect(window.confirm).toHaveBeenCalledWith(
        expect.stringMatching(/accept[\s\S]*completed/i),
      );
      expect(input.onDecide).toHaveBeenCalledExactlyOnceWith(
        'complete',
        undefined,
      );
    },
  );

  it('cancels completion without a decision or changing the selected Epic', () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    const input = props();
    render(<ActionItemProposalDecision {...input} />);
    fireEvent.click(
      screen.getByRole('button', { name: `Complete ${proposal.target_name}` }),
    );
    expect(input.onDecide).not.toHaveBeenCalled();
  });

  it.each([
    { busy: true, saving: false, approveDisabled: false },
    { busy: true, saving: true, approveDisabled: false },
    { busy: false, saving: false, approveDisabled: true },
  ])('shares acceptance guards for %j', (guards) => {
    const input = props();
    render(<ActionItemProposalDecision {...input} {...guards} />);
    const complete = screen.getByRole('button', {
      name: `Complete ${proposal.target_name}`,
    });
    expect(complete).toBeDisabled();
    fireEvent.click(complete);
    expect(input.onDecide).not.toHaveBeenCalled();
    expect(window.confirm).not.toHaveBeenCalled();
  });

  it('completes using the earlier reviewed parent and destination after catalog refresh', () => {
    const destination = epicGroup(10, []).epic;
    const parent = epicReference(epicGroup(20, []).epic);
    const input = {
      ...props(),
      proposal: { ...proposal, current_parent: parent },
      catalog: { data: { items: [destination] }, loading: false, error: null },
    };
    const view = render(<ActionItemProposalDecision {...input} />);
    chooseEpic(screen.getByRole('button', { name: /Epic for/ }), '10');
    view.rerender(
      <ActionItemProposalDecision
        {...input}
        proposal={{
          ...input.proposal,
          current_parent: {
            ...parent,
            expected_revision: 9,
            cohort: 'new-parent',
          },
        }}
        catalog={{
          ...input.catalog,
          data: {
            items: [{ ...destination, revision: 8, cohort: 'new-destination' }],
          },
        }}
      />,
    );
    fireEvent.click(
      screen.getByRole('button', { name: `Complete ${proposal.target_name}` }),
    );
    expect(input.onDecide).toHaveBeenCalledExactlyOnceWith('complete', {
      expected_parent: parent,
      destination: epicReference(destination),
    });
  });
});
