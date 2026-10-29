import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, screen } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { POLL_INTERVAL_MS } from '../../constants';
import { MeetingDetailPage } from '../MeetingDetailPage';
import { meetingFixture } from './meetingFixture';

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useParams: () => ({ id: meetingFixture.id }) };
});
vi.mock('../../api', () => ({ api: { meetings: { get: vi.fn(), transcript: vi.fn(), deleteTranscript: vi.fn(), retryTranscript: vi.fn() } } }));
import { api } from '../../api';

const mockGet = vi.mocked(api.meetings.get);

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockResolvedValue(meetingFixture);
  vi.mocked(api.meetings.transcript).mockResolvedValue({ status: 'not_imported', items: [], total: 0, limit: 100, offset: 0, error_type: null, captured_at: null });
});

afterEach(() => vi.useRealTimers());

describe('MeetingDetailPage', () => {
  it('renders Markdown summary, provenance, metadata and original link', async () => {
    renderWithProviders(<MeetingDetailPage />);

    expect(screen.getByText('Loading meeting...')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Product planning' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Decisions' })).toBeInTheDocument();
    expect(screen.getByText('Ship the next release.')).toBeInTheDocument();
    expect(screen.getByText('granola')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText(/Alex/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open original meeting' })).toHaveAttribute('href', meetingFixture.source_url);
    expect(screen.getByRole('link', { name: 'Back to meetings' })).toHaveAttribute('href', '/meetings');
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
    expect(screen.getByRole('link', { name: 'Back to meetings' })).toBeInTheDocument();
  });

  it('keeps the saved summary visible if the transcript reader fails', async () => {
    vi.mocked(api.meetings.transcript).mockRejectedValue(new Error('Transcript reader unavailable'));
    renderWithProviders(<MeetingDetailPage />);

    expect(await screen.findByText('Ship the next release.')).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load transcript');
    expect(screen.getByRole('heading', { name: 'Product planning' })).toBeInTheDocument();
  });

  it('refreshes saved summaries periodically', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<MeetingDetailPage />);
    await screen.findByRole('heading', { name: 'Product planning' });
    mockGet.mockResolvedValue({ ...meetingFixture, summary_markdown: 'Updated summary' });

    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(await screen.findByText('Updated summary')).toBeInTheDocument();
  });
});
