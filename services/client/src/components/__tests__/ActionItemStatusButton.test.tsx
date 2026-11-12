import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { ActionItemStatusButton } from '../ActionItemStatusButton';

afterEach(() => vi.restoreAllMocks());

describe('ActionItemStatusButton', () => {
  it('uses the supplied resource noun for completion confirmation', () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderWithProviders(
      <ActionItemStatusButton
        noun="discussion topic"
        item={{ title: 'Budget', status: 'open' }}
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Complete Budget' }));
    expect(confirm).toHaveBeenCalledWith('Complete discussion topic “Budget”?');
  });
  it.each([false, true])(
    'requires confirmation before completing with iconOnly=%s',
    (iconOnly) => {
      const confirm = vi
        .spyOn(window, 'confirm')
        .mockReturnValueOnce(false)
        .mockReturnValueOnce(true);
      const change = vi.fn();
      renderWithProviders(
        <ActionItemStatusButton
          item={{ title: 'Review security', status: 'open' }}
          onChange={change}
          small
          iconOnly={iconOnly}
        />,
      );
      const button = screen.getByRole('button', {
        name: 'Complete Review security',
      });
      if (iconOnly) {
        expect(button).toHaveTextContent('');
        expect(button).toHaveAttribute('title', 'Complete');
      } else expect(button).toHaveTextContent('Complete');
      expect(button).toHaveClass('btn', 'btn-sm', 'btn-success');
      fireEvent.click(button);
      expect(confirm).toHaveBeenCalledWith(
        'Complete action item “Review security”?',
      );
      expect(change).not.toHaveBeenCalled();
      fireEvent.click(button);
      expect(change).toHaveBeenCalledTimes(1);
    },
  );

  it.each([false, true])(
    'keeps reopening immediate with iconOnly=%s',
    (iconOnly) => {
      const confirm = vi.spyOn(window, 'confirm');
      const change = vi.fn();
      renderWithProviders(
        <ActionItemStatusButton
          item={{ title: 'Review security', status: 'completed' }}
          onChange={change}
          iconOnly={iconOnly}
        />,
      );
      const button = screen.getByRole('button', {
        name: 'Reopen Review security',
      });
      expect(button).not.toHaveClass('btn-success');
      fireEvent.click(button);
      expect(confirm).not.toHaveBeenCalled();
      expect(change).toHaveBeenCalledTimes(1);
    },
  );

  it('does not confirm or write when disabled', () => {
    const confirm = vi.spyOn(window, 'confirm');
    const change = vi.fn();
    renderWithProviders(
      <ActionItemStatusButton
        item={{ title: 'Review security', status: 'open' }}
        onChange={change}
        disabled
      />,
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Complete Review security' }),
    );
    expect(confirm).not.toHaveBeenCalled();
    expect(change).not.toHaveBeenCalled();
  });
});
