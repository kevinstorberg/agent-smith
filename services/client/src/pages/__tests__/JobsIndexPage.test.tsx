import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { JobsIndexPage } from '../JobsIndexPage';

const mockNavigate = vi.fn();

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockSetLimit = vi.fn();
const mockSetOffset = vi.fn();
const mockRefresh = vi.fn();

vi.mock('../../hooks/usePagination', () => ({
  usePagination: vi.fn(),
}));

vi.mock('../../api', () => ({
  api: { jobs: { list: vi.fn() } },
}));

import { usePagination } from '../../hooks/usePagination';

const mockUsePagination = usePagination as ReturnType<typeof vi.fn>;

const fakeJobs = [
  { id: 1, name: 'Backup', schedule_config: { hours: 24 }, input_params: {}, description: null, version: 1, created_at: '2026-01-15T10:00:00Z', updated_at: '2026-01-15T10:00:00Z' },
  { id: 2, name: 'Sync', schedule_config: { minutes: 5 }, input_params: { command: 'sync' }, description: null, version: 1, created_at: '2026-02-20T14:30:00Z', updated_at: '2026-02-20T14:30:00Z' },
];

function paginationReturn(overrides = {}) {
  return {
    items: fakeJobs, total: 2, loading: false, limit: 10, offset: 0,
    setLimit: mockSetLimit, setOffset: mockSetOffset, setItems: vi.fn(), refresh: mockRefresh,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockUsePagination.mockReturnValue(paginationReturn());
});

describe('JobsIndexPage', () => {
  it('renders the jobs table with data', () => {
    renderWithProviders(<JobsIndexPage />);
    expect(screen.getByText('Jobs')).toBeInTheDocument();
    expect(screen.getByText('Backup')).toBeInTheDocument();
    expect(screen.getByText('Sync')).toBeInTheDocument();
    expect(screen.getByText('every 5 minutes')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    mockUsePagination.mockReturnValue(paginationReturn({ items: [], total: 0, loading: true }));
    renderWithProviders(<JobsIndexPage />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('shows empty state when no jobs exist', () => {
    mockUsePagination.mockReturnValue(paginationReturn({ items: [], total: 0 }));
    renderWithProviders(<JobsIndexPage />);
    expect(screen.getByText('No jobs found')).toBeInTheDocument();
  });

  it('navigates to new job on button click', () => {
    renderWithProviders(<JobsIndexPage />);
    fireEvent.click(screen.getByText('+ New Job'));
    expect(mockNavigate).toHaveBeenCalledWith('/jobs/new');
  });

  it('navigates to job detail on row click', () => {
    renderWithProviders(<JobsIndexPage />);
    fireEvent.click(screen.getByText('Backup'));
    expect(mockNavigate).toHaveBeenCalledWith('/jobs/1');
  });

  it('polls the current jobs page every 15 seconds', () => {
    vi.useFakeTimers();
    const { unmount } = renderWithProviders(<JobsIndexPage />);

    vi.advanceTimersByTime(15_000);
    expect(mockRefresh).toHaveBeenCalledWith({ showLoading: false });

    unmount();
    mockRefresh.mockClear();
    vi.advanceTimersByTime(15_000);
    expect(mockRefresh).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});
