import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NotificationBar } from '../NotificationBar';

const mockDismiss = vi.fn();
vi.mock('../../context/useNotification', () => ({
  useNotification: () => ({
    notifications: [
      { id: '1', message: 'Saved successfully', type: 'success' },
      { id: '2', message: 'Something failed', type: 'error' },
    ],
    dismiss: mockDismiss,
  }),
}));

describe('NotificationBar', () => {
  it('renders all notification messages', () => {
    render(<NotificationBar />);
    expect(screen.getByText('Saved successfully')).toBeInTheDocument();
    expect(screen.getByText('Something failed')).toBeInTheDocument();
  });

  it('applies correct CSS class per type', () => {
    render(<NotificationBar />);
    const successEl = screen.getByText('Saved successfully').closest('.notification');
    expect(successEl?.className).toContain('notification-success');
    const errorEl = screen.getByText('Something failed').closest('.notification');
    expect(errorEl?.className).toContain('notification-error');
  });

  it('calls dismiss with correct id on click', () => {
    render(<NotificationBar />);
    const buttons = screen.getAllByLabelText('Dismiss notification');
    fireEvent.click(buttons[0]);
    expect(mockDismiss).toHaveBeenCalledWith('1');
  });
});
