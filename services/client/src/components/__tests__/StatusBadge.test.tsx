import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusBadge } from '../StatusBadge';

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="draft" kind="plan" />);
    expect(screen.getByText('draft')).toBeInTheDocument();
  });

  it.each([
    { status: 'draft', kind: 'plan' },
    { status: 'pending', kind: 'proposal' },
  ] as const)(
    'preserves the theme binding and renders the fallback color for $kind',
    ({ status, kind }) => {
      render(<StatusBadge status={status} kind={kind} />);
      const badge = screen.getByText(status);
      expect(badge.style.color).toBe('var(--info, #3498db)');
      expect(badge).toHaveStyle({ color: '#3498db' });
    },
  );

  it('falls back to default styling for final / unknown statuses', () => {
    render(<StatusBadge status="final" kind="plan" />);
    const badge = screen.getByText('final');
    expect(badge).toBeInTheDocument();
    expect(badge.style.color).toBe('');
  });
});
