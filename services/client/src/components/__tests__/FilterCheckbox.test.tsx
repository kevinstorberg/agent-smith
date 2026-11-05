import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { FilterCheckbox } from '../FilterCheckbox';

it('uses its visible label and emits one native change while the caller controls checked state', async () => {
  const changed = vi.fn();
  const onChange = (event: React.ChangeEvent<HTMLInputElement>) =>
    changed(event.target.checked);
  const { rerender } = render(
    <FilterCheckbox checked={false} onChange={onChange}>
      Meetings only
    </FilterCheckbox>,
  );
  const checkbox = screen.getByRole('checkbox', { name: 'Meetings only' });
  await userEvent.click(screen.getByText('Meetings only'));
  expect(changed).toHaveBeenCalledExactlyOnceWith(true);
  expect(checkbox).not.toBeChecked();
  rerender(
    <FilterCheckbox checked onChange={onChange}>
      Meetings only
    </FilterCheckbox>,
  );
  expect(checkbox).toBeChecked();
  expect(changed).toHaveBeenCalledTimes(1);
});

it('preserves keyboard operation and native input attributes', async () => {
  const onChange = vi.fn();
  render(
    <>
      <FilterCheckbox
        checked={false}
        onChange={onChange}
        id="deadline-toggle"
        name="deadline"
        aria-controls="deadline-details"
        aria-describedby="deadline-help"
      >
        Deadline window
      </FilterCheckbox>
      <section id="deadline-details">Deadline details</section>
      <p id="deadline-help">Include upcoming deadlines</p>
    </>,
  );
  const checkbox = screen.getByRole('checkbox', { name: 'Deadline window' });
  expect(checkbox).toHaveAttribute('id', 'deadline-toggle');
  expect(checkbox).toHaveAttribute('name', 'deadline');
  expect(checkbox).toHaveAttribute('aria-controls', 'deadline-details');
  expect(checkbox).toHaveAccessibleDescription('Include upcoming deadlines');
  await userEvent.tab();
  expect(checkbox).toHaveFocus();
  await userEvent.keyboard(' ');
  expect(onChange).toHaveBeenCalledTimes(1);
});

it('keeps disabled filters inert and out of the keyboard tab order', async () => {
  const onChange = vi.fn();
  render(
    <>
      <FilterCheckbox checked onChange={onChange} disabled>
        Starred only
      </FilterCheckbox>
      <button>Next control</button>
    </>,
  );
  const checkbox = screen.getByRole('checkbox', { name: 'Starred only' });
  expect(checkbox).toBeDisabled();
  await userEvent.click(screen.getByText('Starred only'));
  await userEvent.tab();
  expect(screen.getByRole('button', { name: 'Next control' })).toHaveFocus();
  expect(checkbox).toBeChecked();
  expect(onChange).not.toHaveBeenCalled();
});
