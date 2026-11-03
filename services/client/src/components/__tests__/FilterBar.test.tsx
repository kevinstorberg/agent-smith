import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { FilterBar } from '../FilterBar';

it('freezes search and project together until the current write finishes', () => {
  const onNameChange = vi.fn();
  const onProjectChange = vi.fn();
  const props = { nameValue: 'release', projectValue: 'agent-smith', onNameChange, onProjectChange };
  const { rerender } = render(<FilterBar {...props} disabled />);
  expect(screen.getByRole('textbox', { name: /^Search$/ })).toBeDisabled();
  expect(screen.getByRole('textbox', { name: 'Project scope' })).toBeDisabled();
  fireEvent.change(screen.getByRole('textbox', { name: /^Search$/ }), { target: { value: 'changed' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Project scope' }), { target: { value: 'changed project' } });
  expect(onNameChange).not.toHaveBeenCalled();
  expect(onProjectChange).not.toHaveBeenCalled();

  rerender(<FilterBar {...props} />);
  fireEvent.change(screen.getByRole('textbox', { name: /^Search$/ }), { target: { value: 'changed' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Project scope' }), { target: { value: 'changed project' } });
  expect(onNameChange).toHaveBeenCalledWith('changed');
  expect(onProjectChange).toHaveBeenCalledWith('changed project');
});
