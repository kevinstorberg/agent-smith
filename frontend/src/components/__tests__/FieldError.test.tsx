import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FieldError } from '../FieldError';

describe('FieldError', () => {
  it('renders nothing when no error and below 80%', () => {
    const { container } = render(<FieldError maxLength={100} currentLength={50} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders error message', () => {
    render(<FieldError error="Name is required." />);
    expect(screen.getByText('Name is required.')).toBeInTheDocument();
  });

  it('shows counter at 80% capacity', () => {
    render(<FieldError maxLength={100} currentLength={85} />);
    expect(screen.getByText('85 / 100')).toBeInTheDocument();
  });

  it('does not show counter below 80%', () => {
    const { container } = render(<FieldError maxLength={100} currentLength={79} />);
    expect(container.innerHTML).toBe('');
  });

  it('shows both error and counter', () => {
    render(<FieldError error="Too long" maxLength={40} currentLength={45} />);
    expect(screen.getByText('Too long')).toBeInTheDocument();
    expect(screen.getByText('45 / 40')).toBeInTheDocument();
  });

  it('renders nothing with no props', () => {
    const { container } = render(<FieldError />);
    expect(container.innerHTML).toBe('');
  });
});
