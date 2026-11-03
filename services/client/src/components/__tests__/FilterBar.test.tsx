import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { FilterBar } from '../FilterBar';

it('freezes search, project and reset together until the current write finishes', () => {
  const onNameChange = vi.fn();
  const onProjectChange = vi.fn();
  const onReset = vi.fn();
  const props = { nameValue: 'release', projectValue: 'agent-smith', onNameChange, onProjectChange, onReset };
  const { rerender } = render(<FilterBar {...props} disabled />);
  expect(screen.getByRole('textbox', { name: 'Search', exact: true })).toBeDisabled();
  expect(screen.getByRole('textbox', { name: 'Project scope' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Reset view' })).toBeDisabled();
  fireEvent.change(screen.getByRole('textbox', { name: 'Search', exact: true }), { target: { value: 'changed' } });
  fireEvent.click(screen.getByRole('button', { name: 'Reset view' }));
  expect(onNameChange).not.toHaveBeenCalled();
  expect(onReset).not.toHaveBeenCalled();

  rerender(<FilterBar {...props} />);
  fireEvent.change(screen.getByRole('textbox', { name: 'Search', exact: true }), { target: { value: 'changed' } });
  fireEvent.click(screen.getByRole('button', { name: 'Reset view' }));
  expect(onNameChange).toHaveBeenCalledWith('changed');
  expect(onReset).toHaveBeenCalledOnce();
});
