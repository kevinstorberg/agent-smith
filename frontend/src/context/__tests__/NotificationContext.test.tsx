import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { NotificationProvider } from '../NotificationContext';
import { useNotification } from '../useNotification';

function TestConsumer() {
  const { notifications, notify, dismiss } = useNotification();
  return (
    <div>
      <button onClick={() => notify('hello', 'success')}>Add</button>
      {notifications.map(n => (
        <div key={n.id} data-testid="notification">
          {n.message}
          <button onClick={() => dismiss(n.id)}>Dismiss</button>
        </div>
      ))}
    </div>
  );
}

describe('NotificationProvider', () => {
  it('adds and renders a notification', () => {
    render(<NotificationProvider><TestConsumer /></NotificationProvider>);
    fireEvent.click(screen.getByText('Add'));
    expect(screen.getByText('hello')).toBeInTheDocument();
  });

  it('dismisses a notification', () => {
    render(<NotificationProvider><TestConsumer /></NotificationProvider>);
    fireEvent.click(screen.getByText('Add'));
    fireEvent.click(screen.getByText('Dismiss'));
    expect(screen.queryByTestId('notification')).not.toBeInTheDocument();
  });

  it('auto-dismisses after timeout', () => {
    vi.useFakeTimers();
    render(<NotificationProvider><TestConsumer /></NotificationProvider>);
    fireEvent.click(screen.getByText('Add'));
    expect(screen.getByText('hello')).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(7000); });
    expect(screen.queryByTestId('notification')).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it('ignores empty messages', () => {
    function EmptyNotifier() {
      const { notifications, notify } = useNotification();
      return (
        <div>
          <button onClick={() => notify('', 'error')}>AddEmpty</button>
          <span data-testid="count">{notifications.length}</span>
        </div>
      );
    }
    render(<NotificationProvider><EmptyNotifier /></NotificationProvider>);
    fireEvent.click(screen.getByText('AddEmpty'));
    expect(screen.getByTestId('count').textContent).toBe('0');
  });
});

describe('useNotification', () => {
  it('throws when used outside provider', () => {
    expect(() => render(<TestConsumer />)).toThrow(
      'useNotification must be used within a NotificationProvider'
    );
  });
});
