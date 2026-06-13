import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, act } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { PlansIndexPage } from '../PlansIndexPage';

const mockNavigate = vi.fn();

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockSetLimit = vi.fn();
const mockSetOffset = vi.fn();

vi.mock('../../hooks/usePagination', () => ({
  usePagination: vi.fn(),
}));

vi.mock('../../api', () => ({
  api: {
    plans: {
      list: vi.fn(),
      search: vi.fn(),
    },
  },
}));

import { usePagination } from '../../hooks/usePagination';
import { api } from '../../api';

const mockUsePagination = usePagination as ReturnType<typeof vi.fn>;
const mockSearch = api.plans.search as ReturnType<typeof vi.fn>;

const fakePlans = [
  { id: 1, title: 'Plan Alpha', project: 'proj-a', status: 'final', updated_at: '2026-01-15T10:00:00Z' },
  { id: 2, title: 'Plan Beta', project: null, status: 'draft', updated_at: '2026-02-20T14:30:00Z' },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockUsePagination.mockReturnValue({
    items: fakePlans,
    total: 2,
    loading: false,
    limit: 10,
    offset: 0,
    setLimit: mockSetLimit,
    setOffset: mockSetOffset,
  });
  mockSearch.mockResolvedValue([]);
});

describe('PlansIndexPage', () => {
  it('renders the plans table with data', () => {
    renderWithProviders(<PlansIndexPage />);

    expect(screen.getByText('Plans')).toBeInTheDocument();
    expect(screen.getByText('Plan Alpha')).toBeInTheDocument();
    expect(screen.getByText('Plan Beta')).toBeInTheDocument();
    expect(screen.getByText('proj-a')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    mockUsePagination.mockReturnValue({
      items: [],
      total: 0,
      loading: true,
      limit: 10,
      offset: 0,
      setLimit: mockSetLimit,
      setOffset: mockSetOffset,
    });

    renderWithProviders(<PlansIndexPage />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('shows empty state when no plans exist', () => {
    mockUsePagination.mockReturnValue({
      items: [],
      total: 0,
      loading: false,
      limit: 10,
      offset: 0,
      setLimit: mockSetLimit,
      setOffset: mockSetOffset,
    });

    renderWithProviders(<PlansIndexPage />);
    expect(screen.getByText('No plans found')).toBeInTheDocument();
  });

  it('navigates to new plan on button click', () => {
    renderWithProviders(<PlansIndexPage />);

    fireEvent.click(screen.getByText('+ New Plan'));
    expect(mockNavigate).toHaveBeenCalledWith('/plans/new');
  });

  it('navigates to plan detail on row click', () => {
    renderWithProviders(<PlansIndexPage />);

    fireEvent.click(screen.getByText('Plan Alpha'));
    expect(mockNavigate).toHaveBeenCalledWith('/plans/1');
  });

  it('debounces search and shows results', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const searchResults = [
      { id: 3, title: 'Found Plan', project: 'x', updated_at: '2026-03-01T00:00:00Z' },
    ];
    mockSearch.mockResolvedValue(searchResults);

    renderWithProviders(<PlansIndexPage />);

    const searchInput = screen.getByPlaceholderText('Search by title...');
    fireEvent.change(searchInput, { target: { value: 'Found' } });

    expect(mockSearch).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSearch).toHaveBeenCalledWith('Found');

    vi.useRealTimers();
  });

  it('clears search results when query is emptied', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockSearch.mockResolvedValue([{ id: 3, title: 'Found', project: null, updated_at: '2026-03-01T00:00:00Z' }]);

    renderWithProviders(<PlansIndexPage />);

    const searchInput = screen.getByPlaceholderText('Search by title...');
    fireEvent.change(searchInput, { target: { value: 'test' } });

    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSearch).toHaveBeenCalled();

    fireEvent.change(searchInput, { target: { value: '' } });

    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    expect(screen.getByText('Plan Alpha')).toBeInTheDocument();

    vi.useRealTimers();
  });

  it('resets offset when project filter changes', () => {
    renderWithProviders(<PlansIndexPage />);

    const filterInput = screen.getByPlaceholderText('Filter by project...');
    fireEvent.change(filterInput, { target: { value: 'proj-a' } });

    expect(mockSetOffset).toHaveBeenCalledWith(0);
  });

  it('renders status badges and the status filter', () => {
    renderWithProviders(<PlansIndexPage />);

    ['all', 'draft', 'final'].forEach(s =>
      expect(screen.getByRole('button', { name: s })).toBeInTheDocument(),
    );
    // 'draft' appears as both a filter button and Plan Beta's row badge.
    expect(screen.getAllByText('draft').length).toBeGreaterThanOrEqual(2);

    fireEvent.click(screen.getByRole('button', { name: 'draft' }));
    expect(mockSetOffset).toHaveBeenCalledWith(0);
  });
});
