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

beforeEach(() => {
  vi.clearAllMocks();
  mockUsePagination.mockReturnValue({
    items: fakeEvents,
    setItems: vi.fn(),
    total: 2,
    loading: false,
    limit: 10,
    offset: 0,
    setLimit: mockSetLimit,
    setOffset: mockSetOffset,
    refresh: mockRefresh,
  });
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

    fireEvent.click(await screen.findByText(/claude \(1\)/)); // wait for counts to load

    expect(mockSetOffset).toHaveBeenCalledWith(0);
  });

  it('navigates to detail on row click', () => {
    renderWithProviders(<AuditIndexPage />);

    fireEvent.click(screen.getByText('Bash'));

    expect(mockNavigate).toHaveBeenCalledWith('/audit/1');
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
