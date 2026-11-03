import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { describe, it, expect, vi } from 'vitest';
import { DetailPageHeader } from '../DetailPageHeader';

function Location() {
  const location = useLocation();
  return <output aria-label="Current route">{location.pathname}</output>;
}

describe('DetailPageHeader', () => {
  it('returns to its explicit resource route when the detail page was opened directly', () => {
    render(<MemoryRouter initialEntries={['/items/42']}>
      <Location />
      <Routes>
        <Route path="/items/42" element={<DetailPageHeader backTo={{ label: 'items', path: '/items' }} editing={false} saving={false} showActions={false} />} />
        <Route path="/items" element={<h1>Items</h1>} />
      </Routes>
    </MemoryRouter>);
    const back = screen.getByRole('link', { name: /Back to items/ });
    expect(back).toHaveAttribute('href', '/items');
    fireEvent.click(back);
    expect(screen.getByLabelText('Current route')).toHaveTextContent('/items');
    expect(screen.getByRole('heading', { name: 'Items' })).toBeVisible();
  });

  it('retains a custom navigation guard without navigating around it', () => {
    const guard = vi.fn();
    render(<MemoryRouter initialEntries={['/items/42']}>
      <Location />
      <DetailPageHeader backTo={{ label: 'items', path: '/items' }} editing saving={false} onNavigateBack={guard} />
    </MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: /Back to items/ }));
    expect(guard).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('Current route')).toHaveTextContent('/items/42');
    expect(screen.queryByRole('link', { name: /Back to items/ })).not.toBeInTheDocument();
  });

  it('uses the primary Save action and preserves disabled saving controls', () => {
    const save = vi.fn();
    const { rerender } = render(<MemoryRouter><DetailPageHeader backTo={{ label: 'items', path: '/items' }}
      editing saving={false} onSave={save} /></MemoryRouter>);
    expect(screen.getByRole('button', { name: 'Save' })).toHaveClass('btn-primary');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(save).toHaveBeenCalledTimes(1);
    rerender(<MemoryRouter><DetailPageHeader backTo={{ label: 'items', path: '/items' }} editing saving onSave={save} /></MemoryRouter>);
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  });
});
