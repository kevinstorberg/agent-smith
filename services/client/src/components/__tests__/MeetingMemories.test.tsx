import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import type { MeetingMemories as Memories } from '../../api';
import { POLL_INTERVAL_MS } from '../../constants';
import { MeetingMemories } from '../MeetingMemories';

vi.mock('../../api', () => ({ api: { meetings: { memories: vi.fn(), retryMemories: vi.fn() } } }));
import { api } from '../../api';

const mockRead = vi.mocked(api.meetings.memories);
const mockRetry = vi.mocked(api.meetings.retryMemories);
const done: Memories = {
  status: 'done', reason: null, error_type: null, updated_at: '2026-10-28T12:30:00Z',
  items: [{
    id: 'memory-id', kind: 'decision', content: 'The team agreed to ship next week.',
    evidence: [{ segment_id: 'segment-650', quote: 'We agreed to ship the release next week.' }],
  }],
};

function response(status: Memories['status'], reason: string | null = null): Memories {
  return { ...done, status, reason, items: [] };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockRead.mockResolvedValue(done);
  mockRetry.mockResolvedValue({ success: true });
});

afterEach(() => vi.useRealTimers());

describe('MeetingMemories', () => {
  it('shows generated memories with exact source evidence and existing navigation', async () => {
    renderWithProviders(<MeetingMemories meetingId="meeting-id" />);

    expect(screen.getByText('Loading meeting memories...')).toBeInTheDocument();
    expect(await screen.findByText(done.items[0].content)).toBeInTheDocument();
    expect(screen.getByText('Decision')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Source evidence'));
    expect(screen.getByText(done.items[0].evidence[0].quote)).toBeVisible();
    expect(screen.getByText('Transcript segment-650')).toBeVisible();
    expect(screen.getByRole('link', { name: 'View transcript' })).toHaveAttribute('href', '#meeting-transcript');
    expect(screen.getByRole('link', { name: 'Manage saved memories' })).toHaveAttribute('href', '/memory');
    expect(mockRead).toHaveBeenCalledWith('meeting-id');
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it.each([
    ['not_imported', 'Memory generation has not started. Use Process meeting'],
    ['pending', 'Memory generation is queued for the next meeting import run.'],
    ['running', 'Generating meeting memories...'],
    ['failed', 'Memory generation failed.'],
  ] as const)('distinguishes %s without exposing staged results', async (status, message) => {
    mockRead.mockResolvedValue({ ...done, status, error_type: 'PRIVATE_EXCEPTION_DETAIL' });
    renderWithProviders(<MeetingMemories meetingId="meeting-id" />);

    expect(await screen.findByText(text => text.startsWith(message))).toBeInTheDocument();
    expect(screen.queryByText(done.items[0].content)).not.toBeInTheDocument();
    expect(screen.queryByText('PRIVATE_EXCEPTION_DETAIL')).not.toBeInTheDocument();
    if (status !== 'failed') expect(screen.queryByRole('button', { name: 'Retry generation' })).not.toBeInTheDocument();
  });

  it.each([
    ['transcript_pending', 'Transcript capture is still pending.'],
    ['transcript_deleted', 'the saved transcript was deleted.'],
    ['transcript_unsupported', 'does not provide a transcript'],
    ['transcript_unavailable', 'has no transcript available'],
    ['transcript_failed', 'Retry transcript capture'],
  ])('explains the blocked state: %s', async (reason, expected) => {
    mockRead.mockResolvedValue(response('blocked', reason));
    renderWithProviders(<MeetingMemories meetingId="meeting-id" />);

    expect(await screen.findByText(text => text.includes(expected))).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry generation' })).not.toBeInTheDocument();
  });

  it('renders a completed zero-memory explanation', async () => {
    mockRead.mockResolvedValue(response('done', 'No new durable facts were found.'));
    renderWithProviders(<MeetingMemories meetingId="meeting-id" />);

    expect(await screen.findByText('No new durable facts were found.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Manage saved memories' })).not.toBeInTheDocument();
  });

  it('retries reader errors without displaying private exception messages', async () => {
    mockRead.mockRejectedValueOnce(new Error('PRIVATE_READER_DETAIL'));
    renderWithProviders(<MeetingMemories meetingId="meeting-id" />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load meeting memories. Try again.');
    expect(screen.queryByText(/PRIVATE_READER_DETAIL/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText(done.items[0].content)).toBeInTheDocument();
  });

  it('queues failed generation and polls until the committed result is visible', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockRead.mockResolvedValue(response('failed'));
    renderWithProviders(<MeetingMemories meetingId="meeting-id" />);
    await screen.findByText('Memory generation failed.');

    mockRead.mockResolvedValue(response('pending'));
    fireEvent.click(screen.getByRole('button', { name: 'Retry generation' }));
    await waitFor(() => expect(mockRetry).toHaveBeenCalledWith('meeting-id'));
    await screen.findByText('Memory generation is queued for the next meeting import run.');

    mockRead.mockResolvedValue(response('running'));
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(await screen.findByText('Generating meeting memories...')).toBeInTheDocument();

    mockRead.mockResolvedValue(done);
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(await screen.findByText(done.items[0].content)).toBeInTheDocument();
    mockRead.mockClear();
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(mockRead).not.toHaveBeenCalled();
  });

  it('retains the failed state and shows a safe retry error', async () => {
    mockRead.mockResolvedValue(response('failed'));
    mockRetry.mockRejectedValue(new Error('PRIVATE_QUEUE_DETAIL'));
    renderWithProviders(<MeetingMemories meetingId="meeting-id" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Retry generation' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not queue another attempt. Try again.');
    expect(screen.getByText('Memory generation failed.')).toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE_QUEUE_DETAIL/)).not.toBeInTheDocument();
  });

  it('ignores a result that finishes after unmount', async () => {
    let resolveRead: (value: Memories) => void = () => undefined;
    mockRead.mockReturnValueOnce(new Promise(resolve => { resolveRead = resolve; }));
    const { unmount } = renderWithProviders(<MeetingMemories meetingId="meeting-id" />);
    unmount();

    await act(async () => { resolveRead(done); });
    expect(screen.queryByText(done.items[0].content)).not.toBeInTheDocument();
  });
});
