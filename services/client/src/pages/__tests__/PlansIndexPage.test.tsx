import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { POLL_INTERVAL_MS } from '../../constants';
import { PlansIndexPage } from '../PlansIndexPage';

const navigate = vi.fn();
vi.mock('react-router', async original => ({ ...await original<typeof import('react-router')>(), useNavigate: () => navigate }));
vi.mock('../../api', () => ({ api: { plans: { list: vi.fn(), search: vi.fn() } } }));
import { api } from '../../api';

const plans = [
  { id: 1, title: 'Plan Alpha', project: 'proj-a', status: 'final', updated_at: '2026-01-15T10:00:00Z' },
  { id: 2, title: 'Plan Beta', project: null, status: 'draft', updated_at: '2026-02-20T14:30:00Z' },
];
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.plans.list).mockResolvedValue({ items: plans, total: 25 } as never);
  vi.mocked(api.plans.search).mockResolvedValue([{ ...plans[0], id: 3, title: 'Found plan' }] as never);
});
afterEach(() => vi.useRealTimers());

async function typeSearch(value: string) {
  fireEvent.change(screen.getByPlaceholderText('Search by title...'), { target: { value } });
  await act(async () => { vi.advanceTimersByTime(300); });
}

describe('PlansIndexPage', () => {
  it('renders existing plans and navigates to create/detail pages', async () => {
    renderWithProviders(<PlansIndexPage />);
    await screen.findByText('Plan Alpha');
    expect(screen.getByText('Plan Beta')).toBeInTheDocument();
    expect(screen.getByText('proj-a')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Plan Alpha'));
    expect(navigate).toHaveBeenLastCalledWith('/plans/1');
    fireEvent.click(screen.getByText('+ New Plan'));
    expect(navigate).toHaveBeenLastCalledWith('/plans/new');
  });

  it('keeps search fields mounted while loading and distinguishes empty results', async () => {
    vi.mocked(api.plans.list).mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<PlansIndexPage />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search by title...')).toBeInTheDocument();
    expect(await screen.findByText('No plans found')).toBeInTheDocument();
  });

  it('coalesces typing into one search request without requiring Enter or a button', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<PlansIndexPage />);
    await screen.findByText('Plan Alpha');
    const input = screen.getByPlaceholderText('Search by title...');
    input.focus();
    fireEvent.change(input, { target: { value: 'Fo' } });
    await act(async () => { vi.advanceTimersByTime(200); });
    fireEvent.change(input, { target: { value: 'Found' } });
    await act(async () => { vi.advanceTimersByTime(299); });
    expect(api.plans.search).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(api.plans.search).toHaveBeenCalledTimes(1);
    expect(api.plans.search).toHaveBeenCalledWith('Found', { project: undefined, status: undefined });
    expect(input).toHaveFocus();
    expect(screen.getByText('Found plan')).toBeInTheDocument();
  });

  it('resets paging before a debounced project request and combines project/status with search', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<PlansIndexPage />);
    await screen.findByText('Plan Alpha');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(api.plans.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 })));
    vi.mocked(api.plans.list).mockClear();
    fireEvent.change(screen.getByPlaceholderText('Filter by project...'), { target: { value: 'proj-a' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(api.plans.list).toHaveBeenCalledTimes(1);
    expect(api.plans.list).toHaveBeenCalledWith({ limit: 10, offset: 0, project: 'proj-a', status: undefined });
    await typeSearch('Found');
    fireEvent.click(screen.getByRole('button', { name: 'draft' }));
    await waitFor(() => expect(api.plans.search).toHaveBeenLastCalledWith('Found', { project: 'proj-a', status: 'draft' }));
  });

  it('ignores late search responses after clearing and preserves the current list', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let complete!: (items: never[]) => void;
    vi.mocked(api.plans.search).mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
    renderWithProviders(<PlansIndexPage />);
    await screen.findByText('Plan Alpha');
    await typeSearch('Old');
    fireEvent.change(screen.getByPlaceholderText('Search by title...'), { target: { value: '' } });
    await screen.findByText('Plan Alpha');
    await act(async () => { complete([{ ...plans[0], title: 'Stale search' }] as never); });
    expect(screen.queryByText('Stale search')).not.toBeInTheDocument();
    expect(screen.getByText('Plan Alpha')).toBeInTheDocument();
  });

  it('shows retryable errors while keeping filters available', async () => {
    vi.mocked(api.plans.list).mockRejectedValueOnce(new Error('private diagnostic'));
    renderWithProviders(<PlansIndexPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load plans.');
    expect(screen.queryByText('private diagnostic')).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search by title...')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Plan Alpha')).toBeInTheDocument();
  });

  it('polls the current search scope and stops on unmount', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { unmount } = renderWithProviders(<PlansIndexPage />);
    await screen.findByText('Plan Alpha');
    await typeSearch('Found');
    vi.mocked(api.plans.search).mockClear();
    vi.mocked(api.plans.list).mockClear();
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(api.plans.search).toHaveBeenCalledWith('Found', { project: undefined, status: undefined });
    expect(api.plans.list).not.toHaveBeenCalled();
    unmount();
    vi.mocked(api.plans.search).mockClear();
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(api.plans.search).not.toHaveBeenCalled();
  });
});
