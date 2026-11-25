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
      expect(screen.getByRole('combobox')).toHaveDisplayValue('No Epic');
      fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
      expect(onDecide).toHaveBeenLastCalledWith('approve', undefined);
      fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
      expect(onDecide).toHaveBeenLastCalledWith('reject');
    },
  );

  it('shows the reviewed current Epic once, including when its catalog is unavailable or renamed', () => {
    const epic = epicGroup(10, []).epic;
    const duplicate = { ...epicGroup(20, []).epic, title: epic.title };
    const onDecide = vi.fn();
    const props = {
      proposal: actionItemProposal({
        current_parent: epicReference(epic),
        current_parent_title: epic.title,
      }),
      catalog: {
        data: { items: [epic, duplicate] },
        loading: false,
        error: null,
      },
      busy: false,
      saving: false,
      approveDisabled: false,
      onDecide,
    };
    const view = render(<ActionItemProposalDecision {...props} />);
    expect(screen.getByRole('combobox')).toHaveDisplayValue(
      `${epic.title} #10`,
    );
    expect(
      screen.getByRole('option', { name: `${epic.title} #10` }),
    ).toHaveValue('');
    expect(
      screen.getByRole('option', { name: `${epic.title} #20` }),
    ).toHaveValue('20');
    expect(screen.getAllByRole('option')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    expect(onDecide).toHaveBeenLastCalledWith('approve', undefined);
    view.rerender(
      <ActionItemProposalDecision
        {...props}
        catalog={{ data: null, loading: false, error: 'Offline' }}
      />,
    );
    expect(screen.getByRole('combobox')).toHaveDisplayValue(epic.title);
    view.rerender(
      <ActionItemProposalDecision
        {...props}
        catalog={{
          ...props.catalog,
          data: {
            items: [{ ...epic, title: 'Renamed elsewhere', revision: 9 }],
          },
        }}
      />,
    );
    expect(screen.getByRole('combobox')).toHaveDisplayValue(epic.title);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    expect(onDecide).toHaveBeenLastCalledWith('approve', undefined);
  });

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
    expect(screen.getByRole('combobox')).toHaveDisplayValue('No Epic');
    view.rerender(
      <ActionItemProposalDecision
        {...props}
        proposal={actionItemProposal({ current_parent: epicReference(epic) })}
      />,
    );
    expect(screen.getByRole('combobox')).toHaveDisplayValue(epic.title);
    expect(screen.queryByText(/^Current:/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    expect(onDecide).toHaveBeenCalledExactlyOnceWith('approve', undefined);
    view.rerender(
      <ActionItemProposalDecision
        {...props}
        proposal={actionItemProposal({ current_parent: epicReference(epic) })}
        catalog={{ data: null, loading: false, error: 'Unavailable' }}
      />,
    );
    expect(screen.getByRole('combobox')).toHaveDisplayValue(
      `Epic #${epic.id} (name unavailable)`,
    );
    view.rerender(
      <ActionItemProposalDecision
        {...props}
        proposal={actionItemProposal({ current_parent: undefined })}
      />,
    );
    expect(screen.queryByText(/^Current:/)).toBeNull();
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
