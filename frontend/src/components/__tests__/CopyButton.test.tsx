import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { CopyButton } from '../CopyButton';

describe('CopyButton', () => {
  beforeEach(() => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it('renders with "Copy" text', () => {
    render(<CopyButton text="hello" />);
    expect(screen.getByText('Copy')).toBeInTheDocument();
  });

  it('copies text to clipboard on click', () => {
    render(<CopyButton text="test content" />);
    fireEvent.click(screen.getByText('Copy'));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('test content');
  });

  it('shows "Copied" after click', () => {
    render(<CopyButton text="hello" />);
    fireEvent.click(screen.getByText('Copy'));
    expect(screen.getByText('Copied')).toBeInTheDocument();
  });

  it('reverts to "Copy" after timeout', () => {
    vi.useFakeTimers();
    render(<CopyButton text="hello" />);
    fireEvent.click(screen.getByText('Copy'));
    expect(screen.getByText('Copied')).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(2000); });
    expect(screen.getByText('Copy')).toBeInTheDocument();
    vi.useRealTimers();
  });

  it('stops event propagation on click', () => {
    const parentClick = vi.fn();
    render(
      <div onClick={parentClick}>
        <CopyButton text="hello" />
      </div>
    );
    fireEvent.click(screen.getByText('Copy'));
    expect(parentClick).not.toHaveBeenCalled();
  });
});
