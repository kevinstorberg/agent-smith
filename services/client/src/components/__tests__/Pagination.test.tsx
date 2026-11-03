import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { Pagination } from '../Pagination';

describe('Pagination', () => {
  it('labels its navigation and identifies the current page without changing page button names', () => {
    render(<Pagination total={45} limit={10} offset={10} onPageChange={vi.fn()} onLimitChange={vi.fn()} />);
    expect(screen.getByRole('navigation', { name: 'Pagination' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '2' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('button', { name: '1' })).not.toHaveAttribute('aria-current');
    expect(screen.getByRole('combobox', { name: 'Rows per page' })).toHaveValue('10');
    expect(screen.getByText('Rows per page', { selector: 'label' })).toBeVisible();
  });

  it('keeps independently rendered page-size labels connected to unique selectors', () => {
    render(<><Pagination total={25} limit={10} offset={0} onPageChange={vi.fn()} onLimitChange={vi.fn()} />
      <Pagination total={50} limit={25} offset={0} onPageChange={vi.fn()} onLimitChange={vi.fn()} /></>);
    const controls = screen.getAllByRole('combobox', { name: 'Rows per page' });
    expect(controls[0].id).not.toBe(controls[1].id);
    expect(controls.map(control => document.querySelector(`label[for="${control.id}"]`))).not.toContain(null);
  });

  it('supports fixed page sizes and locks navigation during an edit', () => {
    const change = vi.fn();
    render(<Pagination total={45} limit={20} offset={0} onPageChange={change} disabled />);
    expect(screen.getByText(/1–20 of 45/)).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(change).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '2' })).toBeDisabled();
  });
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
