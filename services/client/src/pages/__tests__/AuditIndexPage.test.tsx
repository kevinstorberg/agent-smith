import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { POLL_INTERVAL_MS } from '../../constants';
import { AuditIndexPage } from '../AuditIndexPage';

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
  api: { audit: { list: vi.fn(), counts: vi.fn() } },
}));

import { usePagination } from '../../hooks/usePagination';
import { api } from '../../api';

const mockUsePagination = usePagination as ReturnType<typeof vi.fn>;
const mockCounts = api.audit.counts as ReturnType<typeof vi.fn>;

const fakeEvents = [
  {
    id: 1,
    correlation_key: 'toolu_a',
    agent: 'claude',
    session_id: 's1',
    tool_name: 'Bash',
    cwd: '/repo',
    project: 'agent-smith',
    status: 'success',
    created_at: '2026-06-15T10:00:00Z',
    completed_at: '2026-06-15T10:00:01Z',
    duration_ms: 1200,
  },
  {
    id: 2,
    correlation_key: 'toolu_b',
    agent: 'codex',
    session_id: 's2',
    tool_name: 'Read',
    cwd: null,
    project: null,
    status: 'pending',
    created_at: '2026-06-15T10:01:00Z',
    completed_at: null,
    duration_ms: null,
  },
];

function paginationResult() {
  return {
    items: fakeEvents,
    setItems: vi.fn(),
    total: 2,
    loading: false,
    dataCurrent: true,
    limit: 10,
    offset: 0,
    setLimit: mockSetLimit,
    setOffset: mockSetOffset,
    refresh: mockRefresh,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockUsePagination.mockReturnValue(paginationResult());
  mockCounts.mockResolvedValue({ claude: 1, codex: 1, gemini: 0 });
});

describe('AuditIndexPage', () => {
  it('renders events with tool, status, and duration', async () => {
    renderWithProviders(<AuditIndexPage />);

    expect(screen.getByText('Audit Trail')).toBeInTheDocument();
    expect(screen.getByText('Bash')).toBeInTheDocument();
    expect(screen.getByText('Read')).toBeInTheDocument();
    expect(screen.getByText('1200 ms')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument(); // pending event has no duration
    // 'success' appears both as a status filter chip and the row's status badge.
    expect(screen.getAllByText('success').length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByText(/claude \(1\)/)).toBeInTheDocument());
  });

  it('filters by agent and resets paging', async () => {
    renderWithProviders(<AuditIndexPage />);

    await screen.findByText(/claude \(1\)/);
    fireEvent.change(screen.getByRole('combobox', { name: 'Agent' }), { target: { value: 'claude' } });

    expect(mockSetOffset).toHaveBeenCalledWith(0);
  });

  it('navigates to detail on row click', () => {
    renderWithProviders(<AuditIndexPage />);

    const link = screen.getByRole('link', { name: 'Bash' });
    expect(link).toHaveAttribute('href', '/audit/1');
    fireEvent.click(link.closest('tr')!);

    expect(mockNavigate).toHaveBeenCalledWith('/audit/1');
  });

  it('preserves native tool link behavior without activating supplemental row navigation', () => {
    renderWithProviders(<AuditIndexPage />);
    fireEvent.click(screen.getByRole('link', { name: 'Bash' }));
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it.each([
    { loading: true, dataCurrent: false, error: null },
    { loading: false, dataCurrent: false, error: null },
    { loading: false, dataCurrent: false, error: 'Unavailable' },
  ])('keeps filters mounted without claiming empty results during $error/$loading/$dataCurrent', state => {
    mockUsePagination.mockReturnValue({ ...paginationResult(), ...state, items: [], total: 0 });
    renderWithProviders(<AuditIndexPage />);
    expect(screen.getByRole('combobox', { name: 'Agent' })).toBeVisible();
    expect(screen.getByRole('combobox', { name: 'Status' })).toBeVisible();
    expect(screen.queryByText('No tool calls yet')).not.toBeInTheDocument();
    expect(screen.queryByText('0 tool calls')).not.toBeInTheDocument();
    if (state.error) expect(screen.getByRole('alert')).toHaveTextContent('Could not load audit events.');
    else expect(screen.getByRole('status')).toHaveTextContent('Updating…');
  });

  it('announces an in-flight retry without enabling another retry or claiming empty results', () => {
    mockUsePagination.mockReturnValue({ ...paginationResult(), loading: true, error: 'Unavailable', dataCurrent: false, items: [] });
    renderWithProviders(<AuditIndexPage />);
    expect(screen.getByRole('status')).toHaveTextContent('Updating…');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeDisabled();
    expect(screen.queryByText('No tool calls yet')).not.toBeInTheDocument();
  });

  it('polls audit events and counts every 60 seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<AuditIndexPage />);
    await waitFor(() => expect(mockCounts).toHaveBeenCalledTimes(1));

    mockCounts.mockClear();
    vi.advanceTimersByTime(POLL_INTERVAL_MS);

    await waitFor(() => expect(mockRefresh).toHaveBeenCalledWith({ showLoading: false }));
    expect(mockCounts).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
