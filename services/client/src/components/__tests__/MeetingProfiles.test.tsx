import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import type { MeetingProfiles as Profiles } from '../../api';
import { POLL_INTERVAL_MS } from '../../constants';
import { MeetingProfiles } from '../MeetingProfiles';
import { profileFixture } from '../../pages/__tests__/profileFixture';

vi.mock('../../api', () => ({ api: { meetings: { profiles: vi.fn(), retryProfiles: vi.fn() } } }));
import { api } from '../../api';

const read = vi.mocked(api.meetings.profiles);
const retry = vi.mocked(api.meetings.retryProfiles);
const done: Profiles = { status: 'done', items: [profileFixture], reason: null, error_type: null };

beforeEach(() => {
  vi.clearAllMocks();
  read.mockResolvedValue(done);
  retry.mockResolvedValue({ success: true });
});
afterEach(() => vi.useRealTimers());

describe('MeetingProfiles', () => {
  it('links completed participant profiles from the meeting', async () => {
    renderWithProviders(<MeetingProfiles meetingId="meeting-id" />);
    expect(screen.getByText('Loading participant profiles...')).toBeInTheDocument();
    const profile = await screen.findByRole('link', { name: 'Alex' });
    expect(profile).toHaveAttribute('href', `/profiles/${profileFixture.id}`);
    expect(screen.getByRole('heading', { name: 'Participant profiles' })).toBeInTheDocument();
    expect(screen.getByText(/alex@example.test/)).toBeInTheDocument();
  });

  it.each([
    ['not_imported', 'Persona enrichment has not started. Use Process meeting'],
    ['pending', 'Persona enrichment is queued for the next persona job run.'],
    ['running', 'Generating participant profiles...'],
    ['failed', 'Persona enrichment failed.'],
  ] as const)('shows %s without publishing staged profiles', async (status, message) => {
    read.mockResolvedValue({ ...done, status, error_type: 'PRIVATE_DETAIL' });
    renderWithProviders(<MeetingProfiles meetingId="meeting-id" />);
    expect(await screen.findByText(text => text.startsWith(message))).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Alex' })).not.toBeInTheDocument();
    expect(screen.queryByText('PRIVATE_DETAIL')).not.toBeInTheDocument();
  });

  it.each([
    ['transcript_pending', 'complete saved transcript'],
    ['transcript_deleted', 'saved transcript was deleted'],
    ['memories_pending', 'Memory generation runs independently'],
    ['memories_failed', 'Memory generation runs independently'],
  ])('explains blocked generation: %s', async (reason, text) => {
    read.mockResolvedValue({ ...done, status: 'blocked', items: [], reason });
    renderWithProviders(<MeetingProfiles meetingId="meeting-id" />);
    expect(await screen.findByText(value => value.includes(text))).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry generation' })).not.toBeInTheDocument();
  });

  it('shows an empty completion and recovers safely from a reader failure', async () => {
    read.mockRejectedValueOnce(new Error('PRIVATE_READ_DETAIL')).mockResolvedValue({ ...done, items: [], reason: 'No attributable participants were found.' });
    renderWithProviders(<MeetingProfiles meetingId="meeting-id" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load participant profiles.');
    expect(screen.queryByText(/PRIVATE_READ_DETAIL/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No attributable participants were found.')).toBeInTheDocument();
  });

  it('queues a failed stage and polls until profiles are committed', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    read.mockResolvedValue({ ...done, status: 'failed', items: [] });
    renderWithProviders(<MeetingProfiles meetingId="meeting-id" />);
    await screen.findByText('Persona enrichment failed.');
    read.mockResolvedValue({ ...done, status: 'pending', items: [] });
    fireEvent.click(screen.getByRole('button', { name: 'Retry generation' }));
    await waitFor(() => expect(retry).toHaveBeenCalledWith('meeting-id'));
    await screen.findByText('Persona enrichment is queued for the next persona job run.');
    read.mockResolvedValue(done);
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(await screen.findByRole('link', { name: 'Alex' })).toBeInTheDocument();
  });
});
