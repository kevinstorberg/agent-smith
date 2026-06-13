import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusBadge } from '../StatusBadge';

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="draft" kind="plan" />);
    expect(screen.getByText('draft')).toBeInTheDocument();
  });

  it('applies a color for a known plan status', () => {
    render(<StatusBadge status="draft" kind="plan" />);
    expect(screen.getByText('draft')).toHaveStyle({ color: 'var(--info, #3498db)' });
  });

  it('applies a color for a known proposal status', () => {
    render(<StatusBadge status="pending" kind="proposal" />);
    expect(screen.getByText('pending')).toHaveStyle({ color: 'var(--info, #3498db)' });
  });

  it('falls back to default styling for final / unknown statuses', () => {
    render(<StatusBadge status="final" kind="plan" />);
    const badge = screen.getByText('final');
    expect(badge).toBeInTheDocument();
    expect(badge.style.color).toBe('');
  });
});
