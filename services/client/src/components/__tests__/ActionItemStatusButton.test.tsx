import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { ActionItemStatusButton } from '../ActionItemStatusButton';

afterEach(() => vi.restoreAllMocks());

describe('ActionItemStatusButton', () => {
  it('requires confirmation before completing and uses the existing green style', () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    const change = vi.fn();
    renderWithProviders(<ActionItemStatusButton item={{ title: 'Review security', status: 'open' }} onChange={change} small />);
    const button = screen.getByRole('button', { name: 'Complete Review security' });
    expect(button).toHaveTextContent('Complete');
    expect(button).toHaveClass('btn', 'btn-sm', 'btn-success');
    fireEvent.click(button);
    expect(confirm).toHaveBeenCalledWith('Complete action item “Review security”?');
    expect(change).not.toHaveBeenCalled();
    fireEvent.click(button);
    expect(change).toHaveBeenCalledTimes(1);
  });

  it('keeps reopening immediate and uses an ordinary button', () => {
    const confirm = vi.spyOn(window, 'confirm');
    const change = vi.fn();
    renderWithProviders(<ActionItemStatusButton item={{ title: 'Review security', status: 'completed' }} onChange={change} />);
    const button = screen.getByRole('button', { name: 'Reopen Review security' });
    expect(button).not.toHaveClass('btn-success');
    fireEvent.click(button);
    expect(confirm).not.toHaveBeenCalled();
    expect(change).toHaveBeenCalledTimes(1);
  });

  it('does not confirm or write when disabled', () => {
    const confirm = vi.spyOn(window, 'confirm');
    const change = vi.fn();
    renderWithProviders(<ActionItemStatusButton item={{ title: 'Review security', status: 'open' }} onChange={change} disabled />);
    fireEvent.click(screen.getByRole('button', { name: 'Complete Review security' }));
    expect(confirm).not.toHaveBeenCalled();
    expect(change).not.toHaveBeenCalled();
  });
});
