import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { POLL_INTERVAL_MS } from '../../constants';
import { MeetingDetailPage } from '../MeetingDetailPage';
import { meetingFixture } from './meetingFixture';

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useParams: () => ({ id: meetingFixture.id }) };
});
vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { meetings: { get: vi.fn(), transcript: vi.fn(), deleteTranscript: vi.fn(), retryTranscript: vi.fn(), memories: vi.fn(), retryMemories: vi.fn(), profiles: vi.fn(), retryProfiles: vi.fn(), participants: vi.fn(), updateParticipants: vi.fn(), process: vi.fn() }, profiles: { list: vi.fn() } } };
});
import { api } from '../../api';

const mockGet = vi.mocked(api.meetings.get);

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockResolvedValue(meetingFixture);
  vi.mocked(api.meetings.transcript).mockResolvedValue({ status: 'not_imported', items: [], total: 0, limit: 100, offset: 0, error_type: null, captured_at: null });
  vi.mocked(api.meetings.memories).mockResolvedValue({ status: 'not_imported', items: [], reason: null, error_type: null, updated_at: null });
  vi.mocked(api.meetings.profiles).mockResolvedValue({ status: 'not_imported', items: [], reason: null, error_type: null });
  vi.mocked(api.meetings.participants).mockResolvedValue({ revision: 0, items: [], provider_participants: [], speakers: [], running: false, enrolled: false });
  vi.mocked(api.meetings.process).mockResolvedValue({ status: 'queued' });
});

afterEach(() => vi.useRealTimers());

describe('MeetingDetailPage', () => {
  it('renders Markdown summary, provenance, metadata and original link', async () => {
    renderWithProviders(<MeetingDetailPage />);

    expect(screen.getByText('Loading meeting...')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Product planning' })).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Meeting details ·/));
    expect(screen.getByRole('heading', { name: 'Decisions' })).toBeInTheDocument();
    expect(screen.getByText('Ship the next release.')).toBeInTheDocument();
    expect(screen.getByText('granola')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText(/Alex/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open original meeting' })).toHaveAttribute('href', meetingFixture.source_url);
    expect(screen.getByRole('button', { name: /Back to meetings/ })).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith(meetingFixture.id);
  });

  it('uses plain summary text when Markdown is missing', async () => {
    mockGet.mockResolvedValue({ ...meetingFixture, summary_markdown: null, title: null });
    renderWithProviders(<MeetingDetailPage />);

    expect(await screen.findByRole('heading', { name: 'Untitled meeting' })).toBeInTheDocument();
    expect(screen.getByText('Discussed the next release.')).toBeInTheDocument();
  });

  it.each(['javascript:alert(1)', 'data:text/html,<script>bad</script>', '/relative-path'])('does not link to an unsafe source URL: %s', async source_url => {
    mockGet.mockResolvedValue({ ...meetingFixture, source_url });
    renderWithProviders(<MeetingDetailPage />);

    await screen.findByRole('heading', { name: 'Product planning' });
    expect(screen.queryByRole('link', { name: 'Open original meeting' })).not.toBeInTheDocument();
  });

  it('shows missing or failed reads as an error with back navigation', async () => {
    mockGet.mockRejectedValue(new Error('Meeting not found'));
    renderWithProviders(<MeetingDetailPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Meeting not found');
    expect(screen.getByRole('button', { name: /Back to meetings/ })).toBeInTheDocument();
  });

  it('keeps the saved summary visible if the transcript reader fails', async () => {
    vi.mocked(api.meetings.transcript).mockRejectedValue(new Error('Transcript reader unavailable'));
    renderWithProviders(<MeetingDetailPage />);

    expect(await screen.findByText('Ship the next release.')).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load transcript');
    expect(screen.getByRole('heading', { name: 'Product planning' })).toBeInTheDocument();
  });

  it('keeps summary and transcript visible if the memory reader fails', async () => {
    vi.mocked(api.meetings.memories).mockRejectedValue(new Error('Memory reader unavailable'));
    renderWithProviders(<MeetingDetailPage />);

    expect(await screen.findByText('Ship the next release.')).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load meeting memories');
    expect(screen.getByRole('region', { name: 'Meeting transcript' })).toBeInTheDocument();
  });

  it('refreshes saved summaries periodically', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<MeetingDetailPage />);
    await screen.findByRole('heading', { name: 'Product planning' });
    mockGet.mockResolvedValue({ ...meetingFixture, summary_markdown: 'Updated summary' });

    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(await screen.findByText('Updated summary')).toBeInTheDocument();
  });

  it('keeps participant drafts and loaded transcript pages through a failed summary refresh', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let failRefresh: (failure: Error) => void = () => undefined;
    mockGet.mockResolvedValueOnce(meetingFixture).mockReturnValueOnce(new Promise((_, reject) => { failRefresh = reject; }));
    vi.mocked(api.profiles.list).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.meetings.transcript).mockImplementation(async (_id, params) => ({
      status: 'ready', total: 101, offset: params?.offset || 0, limit: 100, error_type: null, captured_at: meetingFixture.updated_at,
      items: Array.from({ length: params?.offset ? 1 : 100 }, (_, index) => ({
        id: `segment-${(params?.offset || 0) + index}`, text: `Saved transcript line ${(params?.offset || 0) + index}`,
        speaker: {}, start_time: null, end_time: null,
      })),
    }));
    renderWithProviders(<MeetingDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Load more transcript' }));
    await screen.findByText('Saved transcript line 100');
    fireEvent.click(screen.getByRole('button', { name: 'Add participant' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'My participant draft' } });
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    await act(async () => { failRefresh(new Error('Temporary failure')); });
    expect(await screen.findByText(/Could not refresh this meeting/)).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('My participant draft');
    expect(screen.getByText('Saved transcript line 100')).toBeInTheDocument();
    mockGet.mockResolvedValue(meetingFixture);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.queryByText(/Could not refresh this meeting/)).not.toBeInTheDocument());
    expect(screen.getByLabelText('Name')).toHaveValue('My participant draft');
    expect(screen.getByText('Saved transcript line 100')).toBeInTheDocument();
    expect(api.meetings.transcript).toHaveBeenCalledTimes(2);
  });

  it('queues an older meeting and refreshes all generated sections without dead-end instructions', async () => {
    renderWithProviders(<MeetingDetailPage />);
    await screen.findByRole('heading', { name: 'Product planning' });
    expect(screen.queryByText(/not processed retroactively/)).not.toBeInTheDocument();
    expect(screen.queryByText(/not enabled for this older meeting/)).not.toBeInTheDocument();
    const before = vi.mocked(api.meetings.transcript).mock.calls.length;
    await waitFor(() => expect(screen.getByRole('button', { name: 'Process meeting' })).not.toBeDisabled());
    fireEvent.click(screen.getByRole('button', { name: 'Process meeting' }));
    await waitFor(() => expect(api.meetings.process).toHaveBeenCalledWith(meetingFixture.id));
    expect(await screen.findByText(/Missing work is queued for your meeting and persona jobs/)).toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(api.meetings.transcript).mock.calls.length).toBeGreaterThan(before));
    expect(vi.mocked(api.meetings.memories).mock.calls.length).toBeGreaterThan(1);
    expect(vi.mocked(api.meetings.profiles).mock.calls.length).toBeGreaterThan(1);
    expect(screen.getByText('Ship the next release.')).toBeInTheDocument();
  });
});
