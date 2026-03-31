import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { Pagination } from '../Pagination';

describe('Pagination', () => {
  it('renders nothing when total is 0', () => {
    const { container } = render(
      <Pagination total={0} limit={10} offset={0} onPageChange={vi.fn()} onLimitChange={vi.fn()} />
    );
    expect(container.innerHTML).toBe('');
  });

  it('shows correct range text', () => {
    render(
      <Pagination total={25} limit={10} offset={0} onPageChange={vi.fn()} onLimitChange={vi.fn()} />
    );
    expect(screen.getByText(/1–10 of 25/)).toBeInTheDocument();
  });

  it('shows correct range on page 2', () => {
    render(
      <Pagination total={25} limit={10} offset={10} onPageChange={vi.fn()} onLimitChange={vi.fn()} />
    );
    expect(screen.getByText(/11–20 of 25/)).toBeInTheDocument();
  });

  it('calls onPageChange when clicking Next', () => {
    const onPageChange = vi.fn();
    render(
      <Pagination total={25} limit={10} offset={0} onPageChange={onPageChange} onLimitChange={vi.fn()} />
    );
    fireEvent.click(screen.getByText('Next'));
    expect(onPageChange).toHaveBeenCalledWith(10);
  });

  it('calls onPageChange when clicking Previous', () => {
    const onPageChange = vi.fn();
    render(
      <Pagination total={25} limit={10} offset={10} onPageChange={onPageChange} onLimitChange={vi.fn()} />
    );
    fireEvent.click(screen.getByText('Previous'));
    expect(onPageChange).toHaveBeenCalledWith(0);
  });

  it('disables Previous on first page', () => {
    render(
      <Pagination total={25} limit={10} offset={0} onPageChange={vi.fn()} onLimitChange={vi.fn()} />
    );
    expect(screen.getByText('Previous')).toBeDisabled();
  });

  it('disables Next on last page', () => {
    render(
      <Pagination total={25} limit={10} offset={20} onPageChange={vi.fn()} onLimitChange={vi.fn()} />
    );
    expect(screen.getByText('Next')).toBeDisabled();
  });

  it('calls onLimitChange when selecting page size', () => {
    const onLimitChange = vi.fn();
    render(
      <Pagination total={50} limit={10} offset={0} onPageChange={vi.fn()} onLimitChange={onLimitChange} />
    );
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '25' } });
    expect(onLimitChange).toHaveBeenCalledWith(25);
  });
});
