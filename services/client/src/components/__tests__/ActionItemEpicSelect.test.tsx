import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ActionItemEpicSelect } from '../ActionItemEpicSelect';
import { epicGroup } from '../../pages/__tests__/actionItemEpicFixture';

const epic = (id: number, title = `Epic ${id}`) => ({
  ...epicGroup(id, []).epic,
  title,
});

describe('controlled searchable Epic selection', () => {
  it('focuses search, disambiguates against the full catalog, and emits only an explicit choice', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ActionItemEpicSelect
        label="Epic"
        value=""
        epics={[epic(10, 'Release'), epic(20, 'Release')]}
        onChange={onChange}
      />,
    );
    const trigger = screen.getByRole('button', { name: 'Epic' });
    await user.click(trigger);
    const search = screen.getByRole('searchbox', { name: 'Find Epic' });
    expect(search).toHaveFocus();
    await user.type(search, '#20');
    expect(
      screen.queryByRole('button', { name: 'Release #10' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Release #20' })).toHaveValue(
      '20',
    );
    expect(trigger).toHaveTextContent('No Epic');
    expect(onChange).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Release #20' }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith('20');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveTextContent('No Epic');
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  });

  it('never changes selection through typing, clearing, unmatched text, Escape or outside dismissal', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <>
        <ActionItemEpicSelect
          label="Epic"
          value="10"
          epics={[epic(10)]}
          onChange={onChange}
        />
        <button>Outside</button>
      </>,
    );
    const trigger = screen.getByRole('button', { name: 'Epic' });
    await user.click(trigger);
    await user.type(screen.getByRole('searchbox'), 'not a match');
    expect(screen.getByText('No matching Epics')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear Epic search' }));
    expect(screen.getByRole('searchbox')).toHaveValue('');
    await user.keyboard('{Escape}');
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    expect(screen.getByRole('searchbox')).toHaveValue('');
    await user.type(screen.getByRole('searchbox'), 'another draft');
    await user.click(screen.getByRole('button', { name: 'Outside' }));
    expect(screen.getByRole('button', { name: 'Outside' })).toHaveFocus();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('prevents form submission and moves search Enter/ArrowDown into results without selecting', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const submit = vi.fn((event) => event.preventDefault());
    render(
      <form onSubmit={submit}>
        <ActionItemEpicSelect
          label="Epic"
          value=""
          epics={[epic(10), epic(20)]}
          onChange={onChange}
        />
      </form>,
    );
    const trigger = screen.getByRole('button', { name: 'Epic' });
    trigger.focus();
    await user.keyboard('{Enter}');
    await user.keyboard('{Enter}');
    expect(screen.getByRole('button', { name: 'Epic 10' })).toHaveFocus();
    expect(onChange).not.toHaveBeenCalled();
    expect(submit).not.toHaveBeenCalled();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('button', { name: 'Epic 20' })).toHaveFocus();
    await user.keyboard('{ArrowUp}{ArrowUp}');
    expect(screen.getByRole('searchbox')).toHaveFocus();
    await user.keyboard('{ArrowDown}{Enter}');
    expect(onChange).toHaveBeenCalledExactlyOnceWith('10');
    expect(submit).not.toHaveBeenCalled();
  });

  it('bounds matching Epic results to twenty and reports the complete count', async () => {
    const user = userEvent.setup();
    render(
      <ActionItemEpicSelect
        label="Epic"
        value=""
        epics={Array.from({ length: 45 }, (_, i) => epic(i + 1))}
        onChange={vi.fn()}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Epic' }));
    expect(
      within(screen.getByRole('list')).getAllByRole('button'),
    ).toHaveLength(20);
    expect(screen.getByRole('status')).toHaveTextContent(
      'Showing 20 of 45 Epics. Refine your search.',
    );
    await user.type(screen.getByRole('searchbox'), 'Epic 45');
    expect(
      within(screen.getByRole('list')).getAllByRole('button'),
    ).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Epic 45' })).toBeInTheDocument();
  });

  it('preserves earlier/current/default choices, omits current Epic and supports explicit creation', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ActionItemEpicSelect
        label="Epic"
        value="earlier"
        defaultLabel="Keep current Epic"
        epics={[epic(10, 'Renamed release'), epic(20)]}
        retainedOption={{ value: 'earlier', label: 'Release — earlier choice' }}
        omitEpicId={20}
        allowCreate
        onChange={onChange}
      />,
    );
    const trigger = screen.getByRole('button', { name: 'Epic' });
    expect(trigger).toHaveTextContent('Release — earlier choice');
    await user.click(trigger);
    expect(
      screen.queryByRole('button', { name: 'Epic 20' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Keep current Epic' }),
    ).toHaveValue('');
    await user.click(screen.getByRole('button', { name: 'Renamed release' }));
    expect(onChange).toHaveBeenLastCalledWith('10');
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: 'New Epic…' }));
    expect(onChange).toHaveBeenLastCalledWith('new');
  });

  it('closes current selection without redundant autosave and preserves unknown selections honestly', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const props = { label: 'Epic', value: '10', epics: [epic(10)], onChange };
    const view = render(<ActionItemEpicSelect {...props} />);
    const trigger = screen.getByRole('button', { name: 'Epic' });
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: 'Epic 10' }));
    expect(onChange).not.toHaveBeenCalled();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    view.rerender(<ActionItemEpicSelect {...props} epics={[]} />);
    expect(trigger).toHaveTextContent('Epic #10 (unavailable)');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('honors disabled/autofocus/description and closes without changing value when becoming busy', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const props = {
      label: 'Epic',
      ariaLabel: 'Destination Epic',
      value: '',
      epics: [epic(10)],
      onChange,
      autoFocus: true,
      ariaDescribedBy: 'context',
    };
    const view = render(
      <>
        <p id="context">Reviewed parent stays frozen.</p>
        <ActionItemEpicSelect {...props} />
      </>,
    );
    const trigger = screen.getByRole('button', { name: 'Destination Epic' });
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAccessibleDescription(
      'No Epic Reviewed parent stays frozen.',
    );
    await user.click(trigger);
    view.rerender(
      <>
        <p id="context">Reviewed parent stays frozen.</p>
        <ActionItemEpicSelect {...props} disabled />
      </>,
    );
    expect(trigger).toBeDisabled();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(onChange).not.toHaveBeenCalled();
  });
});
