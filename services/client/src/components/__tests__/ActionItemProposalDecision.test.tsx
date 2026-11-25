import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ActionItemProposalDecision } from '../ActionItemProposalDecision';
import { epicGroup } from '../../pages/__tests__/actionItemEpicFixture';
import { actionItemProposal } from '../../pages/__tests__/actionItemProposalFixture';
import { epicReference } from '../../utils/actionItemEpics';

describe('proposal Epic choice', () => {
  it.each(['create', 'update'] as const)(
    'keeps the %s default independent of catalog failures',
    (action) => {
      const onDecide = vi.fn();
      render(
        <ActionItemProposalDecision
          proposal={actionItemProposal({ action })}
          catalog={{ data: null, loading: false, error: 'Offline' }}
          busy={false}
          saving={false}
          approveDisabled={false}
          onDecide={onDecide}
        />,
      );
      expect(screen.getByRole('combobox')).toHaveDisplayValue(
        action === 'create' ? 'No Epic' : 'Keep current',
      );
      fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
      expect(onDecide).toHaveBeenLastCalledWith('approve', undefined);
      fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
      expect(onDecide).toHaveBeenLastCalledWith('reject');
    },
  );

  it('describes standalone and grouped current placement without changing the default request', () => {
    const epic = epicGroup(10, []).epic;
    const onDecide = vi.fn();
    const props = {
      proposal: actionItemProposal(),
      catalog: { data: { items: [epic] }, loading: false, error: null },
      busy: false,
      saving: false,
      approveDisabled: false,
      onDecide,
    };
    const view = render(<ActionItemProposalDecision {...props} />);
    expect(screen.getByText('Current placement: No Epic')).toBeVisible();
    view.rerender(
      <ActionItemProposalDecision
        {...props}
        proposal={actionItemProposal({ current_parent: epicReference(epic) })}
      />,
    );
    expect(screen.getByText(`Current placement: ${epic.title}`)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    expect(onDecide).toHaveBeenCalledExactlyOnceWith('approve', undefined);
    view.rerender(
      <ActionItemProposalDecision
        {...props}
        proposal={actionItemProposal({ current_parent: epicReference(epic) })}
        catalog={{ data: null, loading: false, error: 'Unavailable' }}
      />,
    );
    expect(
      screen.getByText(
        `Current placement: Epic #${epic.id} (name unavailable)`,
      ),
    ).toBeVisible();
    view.rerender(
      <ActionItemProposalDecision
        {...props}
        proposal={actionItemProposal({ current_parent: undefined })}
      />,
    );
    expect(screen.queryByText(/^Current placement:/)).toBeNull();
    expect(screen.getByRole('combobox')).toBeDisabled();
  });

  it('freezes both references through catalog and parent changes until explicit reselection', () => {
    const epic = epicGroup(10, []).epic;
    const parent = epicReference(epicGroup(20, []).epic);
    const proposal = actionItemProposal({ current_parent: parent });
    const onDecide = vi.fn();
    const props = {
      proposal,
      catalog: { data: { items: [epic] }, loading: false, error: null },
      busy: false,
      saving: false,
      approveDisabled: false,
      onDecide,
    };
    const view = render(<ActionItemProposalDecision {...props} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '10' } });
    expect(onDecide).not.toHaveBeenCalled();
    const nextEpic = {
      ...epic,
      title: 'Renamed release',
      revision: 9,
      cohort: 'next',
    };
    const nextParent = {
      ...parent,
      expected_revision: 8,
      cohort: 'next-parent',
    };
    view.rerender(
      <ActionItemProposalDecision
        {...props}
        proposal={{ ...proposal, current_parent: nextParent }}
        catalog={{ ...props.catalog, data: { items: [nextEpic] } }}
      />,
    );
    expect(screen.getByRole('combobox')).toHaveDisplayValue(
      `${epic.title} — earlier choice`,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    expect(onDecide).toHaveBeenLastCalledWith('approve', {
      expected_parent: parent,
      destination: epicReference(epic),
    });
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    expect(onDecide).toHaveBeenLastCalledWith('approve', {
      expected_parent: nextParent,
      destination: epicReference(nextEpic),
    });
  });

  it('retains a removed Epic and blocks changes while saving', () => {
    const epic = epicGroup(10, []).epic;
    const onDecide = vi.fn();
    const props = {
      proposal: actionItemProposal({ action: 'create' }),
      catalog: { data: { items: [epic] }, loading: false, error: null },
      busy: false,
      saving: false,
      approveDisabled: false,
      onDecide,
    };
    const view = render(<ActionItemProposalDecision {...props} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '10' } });
    view.rerender(
      <ActionItemProposalDecision
        {...props}
        busy
        saving
        catalog={{ ...props.catalog, data: { items: [] } }}
      />,
    );
    expect(screen.getByRole('combobox')).toHaveDisplayValue(
      `${epic.title} — earlier choice`,
    );
    expect(screen.getByRole('combobox')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled();
    expect(onDecide).not.toHaveBeenCalled();
  });
});
