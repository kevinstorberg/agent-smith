import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { ProposalsIndexPage } from '../ProposalsIndexPage';

const mockNavigate = vi.fn();

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockSetLimit = vi.fn();
const mockSetOffset = vi.fn();
const mockRefresh = vi.fn();
const mockNotify = vi.fn();

vi.mock('../../context/useNotification', async () => {
  const actual = await vi.importActual<typeof import('../../context/useNotification')>('../../context/useNotification');
  return {
    ...actual,
    useNotification: () => ({ notify: mockNotify, notifications: [], dismiss: vi.fn() }),
  };
});

vi.mock('../../hooks/usePagination', () => ({
  usePagination: vi.fn(),
}));

vi.mock('../../api', () => ({
  api: {
    proposals: {
      list: vi.fn(),
      counts: vi.fn(),
      generate: vi.fn(),
      approve: vi.fn(),
      reject: vi.fn(),
    },
  },
}));

import { usePagination } from '../../hooks/usePagination';
import { api } from '../../api';

const mockUsePagination = usePagination as ReturnType<typeof vi.fn>;
const mockCounts = api.proposals.counts as ReturnType<typeof vi.fn>;
const mockGenerate = api.proposals.generate as ReturnType<typeof vi.fn>;
const mockApprove = api.proposals.approve as ReturnType<typeof vi.fn>;
const mockReject = api.proposals.reject as ReturnType<typeof vi.fn>;
const mockSetItems = vi.fn();

const fakeProposals = [
  {
    id: 1,
    title: 'Clarify the DRY rule',
    target_kind: 'rule',
    action: 'update',
    target_name: 'dry',
    status: 'pending',
    created_at: '2026-06-01T10:00:00Z',
  },
  {
    id: 2,
    title: 'Add nightly cleanup job',
    target_kind: 'job',
    action: 'create',
    target_name: 'cleanup',
    status: 'pending',
    created_at: '2026-06-02T10:00:00Z',
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockUsePagination.mockReturnValue({
    items: fakeProposals,
    setItems: mockSetItems,
    total: 2,
    loading: false,
    limit: 10,
    offset: 0,
    setLimit: mockSetLimit,
    setOffset: mockSetOffset,
    refresh: mockRefresh,
  });
  mockCounts.mockResolvedValue({ pending: 2, approved: 1, rejected: 0 });
  mockGenerate.mockResolvedValue({ started: true, job_id: 7 });
  mockApprove.mockResolvedValue({ id: 1, status: 'approved' });
  mockReject.mockResolvedValue({ id: 1, status: 'rejected' });
});

describe('ProposalsIndexPage', () => {
  it('renders proposals with kind and target', async () => {
    renderWithProviders(<ProposalsIndexPage />);

    expect(screen.getByText('Proposals')).toBeInTheDocument();
    expect(screen.getByText('Clarify the DRY rule')).toBeInTheDocument();
    expect(screen.getByText('Add nightly cleanup job')).toBeInTheDocument();
    expect(screen.getByText('dry')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/pending \(2\)/)).toBeInTheDocument());
  });

  it('switches the status filter and resets paging', () => {
    renderWithProviders(<ProposalsIndexPage />);

    fireEvent.click(screen.getByText(/approved/));

    expect(mockSetOffset).toHaveBeenCalledWith(0);
  });

  it('navigates to the detail page on row click', () => {
    renderWithProviders(<ProposalsIndexPage />);

    fireEvent.click(screen.getByText('Clarify the DRY rule'));

    expect(mockNavigate).toHaveBeenCalledWith('/proposals/1');
  });

  it('quick-approves a row without navigating', async () => {
    renderWithProviders(<ProposalsIndexPage />);

    fireEvent.click(screen.getAllByText('Approve')[0]);

    await waitFor(() => expect(mockApprove).toHaveBeenCalledWith(1));
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(mockSetItems).toHaveBeenCalled();
    await waitFor(() =>
      expect(mockNotify).toHaveBeenCalledWith(expect.stringMatching(/applied/), 'success'),
    );
  });

  it('quick-rejects a row and surfaces conflicts as errors', async () => {
    mockReject.mockRejectedValue(new Error('proposal 2 is approved, not pending'));
    renderWithProviders(<ProposalsIndexPage />);

    fireEvent.click(screen.getAllByText('Reject')[1]);

    await waitFor(() => expect(mockReject).toHaveBeenCalledWith(2));
    await waitFor(() =>
      expect(mockNotify).toHaveBeenCalledWith(expect.stringMatching(/reject failed/), 'error'),
    );
  });

  it('triggers manual generation from the button', async () => {
    renderWithProviders(<ProposalsIndexPage />);

    fireEvent.click(screen.getByText('Generate now'));

    await waitFor(() => expect(mockGenerate).toHaveBeenCalled());
    await waitFor(() =>
      expect(mockNotify).toHaveBeenCalledWith(expect.stringMatching(/Generation started/), 'success'),
    );
  });

  it('surfaces generate errors (e.g. job not seeded)', async () => {
    mockGenerate.mockRejectedValue(new Error("No background job named 'improvement-proposals'"));
    renderWithProviders(<ProposalsIndexPage />);

    fireEvent.click(screen.getByText('Generate now'));

    await waitFor(() =>
      expect(mockNotify).toHaveBeenCalledWith(expect.stringMatching(/No background job named/), 'error'),
    );
  });

  it('polls proposals and counts every 15 seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<ProposalsIndexPage />);
    await waitFor(() => expect(mockCounts).toHaveBeenCalledTimes(1));

    mockCounts.mockClear();
    vi.advanceTimersByTime(15_000);

    await waitFor(() => expect(mockRefresh).toHaveBeenCalledWith({ showLoading: false }));
    expect(mockCounts).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
