import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import type { MeetingTranscript as Transcript } from '../../api';
import { POLL_INTERVAL_MS } from '../../constants';
import { MeetingTranscript } from '../MeetingTranscript';

vi.mock('../../api', () => ({
  api: { meetings: { transcript: vi.fn(), deleteTranscript: vi.fn(), retryTranscript: vi.fn() } },
}));
import { api } from '../../api';

const mockRead = vi.mocked(api.meetings.transcript);
const mockDelete = vi.mocked(api.meetings.deleteTranscript);
const mockRetry = vi.mocked(api.meetings.retryTranscript);
const ready: Transcript = {
  status: 'ready', total: 1, limit: 100, offset: 0, error_type: null, captured_at: '2026-10-28T12:30:00Z',
  transcript_hash: 'b'.repeat(64),
  items: [{
    id: 'segment-0', text: 'We should ship the release next week.',
    speaker: { name: 'Alex', attribution: 'provider', source: 'granola' },
    start_time: '2026-10-28T12:00:00Z', end_time: '2026-10-28T12:00:03Z',
  }],
};

function statusResponse(status: Transcript['status']): Transcript {
  return { ...ready, status, total: 0, items: [], captured_at: null };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockRead.mockResolvedValue(ready);
  mockDelete.mockResolvedValue({ deleted: true, id: 'meeting-id' });
  mockRetry.mockResolvedValue({ success: true });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('MeetingTranscript', () => {
  it('keeps each displayed statement bound to the hash of the page that supplied it', async () => {
    const assign = vi.fn();
    mockRead.mockImplementation(async (_id, params) => ({ ...ready, total: 2, offset: params?.offset || 0,
      transcript_hash: (params?.offset ? 'c' : 'b').repeat(64),
      items: [{ ...ready.items[0], id: `segment-${params?.offset || 0}`, text: params?.offset ? 'New page statement' : 'Original page statement' }],
    }));
    renderWithProviders(<MeetingTranscript meetingId="meeting-id" onAssign={assign} />);
    await screen.findByText('Original page statement');
    fireEvent.click(screen.getByRole('button', { name: 'Load more transcript' }));
    await screen.findByText('New page statement');
    const buttons = screen.getAllByRole('button', { name: 'Assign this statement' });
    fireEvent.click(buttons[0]); fireEvent.click(buttons[1]);
    expect(assign.mock.calls[0][1]).toBe('b'.repeat(64));
    expect(assign.mock.calls[1][1]).toBe('c'.repeat(64));
  });

  it('refreshes effective assignments across loaded pages without resetting transcript pagination or raw speakers', async () => {
    let identified = false;
    mockRead.mockImplementation(async (_id, params) => ({ ...ready, total: 200, offset: params?.offset || 0,
      items: Array.from({ length: 100 }, (_, index) => ({ ...ready.items[0], id: `segment-${(params?.offset || 0) + index}`,
        text: `Line ${(params?.offset || 0) + index}`, speaker: { name: 'Me', source: 'microphone' },
        effective_speaker: identified ? { profile_id: 'known-profile', display_name: 'Confirmed person', email: 'person@example.test', source: 'manual_assignment' as const } : null,
      })),
    }));
    const { rerender } = renderWithProviders(<MeetingTranscript meetingId="meeting-id" refreshVersion={0} />);
    await screen.findByText('Line 99');
    fireEvent.click(screen.getByRole('button', { name: 'Load more transcript' }));
    await screen.findByText('Line 199');
    identified = true;
    rerender(<MeetingTranscript meetingId="meeting-id" refreshVersion={1} />);
    expect(screen.getByText('Line 199')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByRole('link', { name: 'Confirmed person' })).toHaveLength(200));
    expect(screen.getByText('Line 199')).toBeInTheDocument();
    expect(screen.getAllByText('Original: Me · microphone')).toHaveLength(200);
    expect(screen.queryByRole('button', { name: 'Load more transcript' })).not.toBeInTheDocument();
    expect(mockRead.mock.calls.map(call => call[1]?.offset)).toEqual([0, 100, 0, 100]);
  });

  it('renders transcript text, supplied speaker attribution and source timestamps', async () => {
    renderWithProviders(<MeetingTranscript meetingId="meeting-id" />);
    expect(screen.getByText('Loading transcript...')).toBeInTheDocument();
    expect(await screen.findByText(ready.items[0].text)).toBeInTheDocument();
    expect(screen.getByText('Alex')).toBeInTheDocument();
    expect(screen.getByText('provider')).toBeInTheDocument();
    const segment = document.getElementById('transcript-segment-0');
    expect(segment?.querySelector('time')).toHaveAttribute('datetime', ready.items[0].start_time);
    expect(mockRead).toHaveBeenCalledWith('meeting-id', { limit: 100, offset: 0 });
  });

  it('keeps unidentified speakers distinct without inventing a person', async () => {
    mockRead.mockResolvedValue({ ...ready, items: [
      { ...ready.items[0], id: 'segment-0', speaker: { diarization_label: 'Speaker 1' } },
      { ...ready.items[0], id: 'segment-1', speaker: {}, text: 'Unknown contribution.' },
    ], total: 2 });
    renderWithProviders(<MeetingTranscript meetingId="meeting-id" />);

    expect(await screen.findByText('Speaker 1 (unidentified)')).toBeInTheDocument();
    expect(screen.getByText('Unknown speaker')).toBeInTheDocument();
    expect(screen.queryByText('Alex')).not.toBeInTheDocument();
  });

  it('loads additional pages while preserving earlier segments', async () => {
    mockRead.mockResolvedValueOnce({ ...ready, total: 2 }).mockResolvedValueOnce({
      ...ready, offset: 1, total: 2,
      items: [{ ...ready.items[0], id: 'segment-1', text: 'Follow-up discussion.' }],
    });
    renderWithProviders(<MeetingTranscript meetingId="meeting-id" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Load more transcript' }));
    expect(await screen.findByText('Follow-up discussion.')).toBeInTheDocument();
    expect(screen.getByText(ready.items[0].text)).toBeInTheDocument();
    expect(mockRead).toHaveBeenLastCalledWith('meeting-id', { limit: 100, offset: 1 });
    expect(screen.queryByRole('button', { name: 'Load more transcript' })).not.toBeInTheDocument();
  });

  it.each([
    ['not_imported', 'Transcript not imported yet. Use Process meeting'],
    ['pending', 'Transcript capture is pending.'],
    ['capturing', 'Importing transcript...'],
    ['unsupported', 'This meeting connection does not support transcripts.'],
    ['unavailable', 'The meeting provider has no transcript available.'],
    ['failed', 'Transcript import failed.'],
    ['deleted', 'Saved transcript deleted.'],
  ] as const)('shows the %s state accurately', async (status, message) => {
    mockRead.mockResolvedValue(statusResponse(status));
    renderWithProviders(<MeetingTranscript meetingId="meeting-id" />);

    expect(await screen.findByText(text => text.startsWith(message))).toBeInTheDocument();
    if (status === 'not_imported' || status === 'deleted') {
      expect(screen.queryByRole('button', { name: 'Retry capture' })).not.toBeInTheDocument();
    }
  });

  it('shows network failures locally and retries the reader', async () => {
    mockRead.mockRejectedValueOnce(new Error('Reader unavailable'));
    renderWithProviders(<MeetingTranscript meetingId="meeting-id" />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load transcript: Reader unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText(ready.items[0].text)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('requires confirmation before deleting and then shows the retained tombstone', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderWithProviders(<MeetingTranscript meetingId="meeting-id" />);
    const remove = await screen.findByRole('button', { name: 'Delete saved transcript' });
    fireEvent.click(remove);
    expect(mockDelete).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    mockRead.mockResolvedValue(statusResponse('deleted'));
    fireEvent.click(remove);
    expect(await screen.findByText(/Saved transcript deleted/)).toBeInTheDocument();
    expect(mockDelete).toHaveBeenCalledWith('meeting-id');
    expect(screen.queryByText(ready.items[0].text)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry capture' })).not.toBeInTheDocument();
  });

  it('queues retry capture and polls pending capture until ready', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockRead.mockResolvedValue(statusResponse('failed'));
    renderWithProviders(<MeetingTranscript meetingId="meeting-id" />);
    expect(await screen.findByText('Transcript import failed.')).toBeInTheDocument();

    mockRead.mockResolvedValue(statusResponse('pending'));
    fireEvent.click(screen.getByRole('button', { name: 'Retry capture' }));
    await waitFor(() => expect(mockRetry).toHaveBeenCalledWith('meeting-id'));
    expect(await screen.findByText('Transcript capture is pending.')).toBeInTheDocument();

    mockRead.mockResolvedValue(ready);
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(await screen.findByText(ready.items[0].text)).toBeInTheDocument();
    mockRead.mockClear();
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(mockRead).not.toHaveBeenCalled();
  });

  it('ignores a read that completes after this viewer unmounts', async () => {
    let resolveRead: (value: Transcript) => void = () => undefined;
    mockRead.mockReturnValueOnce(new Promise(resolve => { resolveRead = resolve; }));
    const { unmount } = renderWithProviders(<MeetingTranscript meetingId="meeting-id" />);
    unmount();

    await act(async () => { resolveRead(ready); });
    expect(screen.queryByText(ready.items[0].text)).not.toBeInTheDocument();
  });

  it('disables statement assignment while another participant draft or save is active', async () => {
    const assign = vi.fn();
    renderWithProviders(<MeetingTranscript meetingId="meeting-id" onAssign={assign} assignmentDisabled />);
    const button = (await screen.findAllByRole('button', { name: 'Assign this statement' }))[0];
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(assign).not.toHaveBeenCalled();
  });
});
