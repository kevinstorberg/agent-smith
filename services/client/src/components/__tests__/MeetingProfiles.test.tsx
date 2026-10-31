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
  it('shows linked profiles with plain names and a separate view action', async () => {
    renderWithProviders(<MeetingProfiles meetingId="meeting-id" />);
    expect(screen.getByText('Loading participant profiles...')).toBeInTheDocument();
    const profile = await screen.findByRole('link', { name: "View Alex's profile" });
    expect(profile).toHaveAttribute('href', `/profiles/${profileFixture.id}`);
    expect(screen.getByRole('heading', { name: 'Linked profiles' })).toBeInTheDocument();
    expect(screen.getByText('Alex').closest('a')).toBeNull();
    expect(screen.getByRole('link', { name: 'Manage participants' })).toHaveAttribute('href', '#meeting-participants');
    expect(screen.getByText(/alex@example.test/)).toBeInTheDocument();
  });

  it.each([
    ['not_imported', 'Persona enrichment has not started. Use Process meeting'],
    ['pending', 'Persona enrichment is queued for the next persona job run.'],
    ['running', 'Generating participant profiles...'],
    ['failed', 'Persona enrichment failed.'],
  ] as const)('keeps already-linked profiles visible while analysis is %s', async (status, message) => {
    read.mockResolvedValue({ ...done, status, error_type: 'PRIVATE_DETAIL' });
    renderWithProviders(<MeetingProfiles meetingId="meeting-id" />);
    expect(await screen.findByText(text => text.startsWith(message))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: "View Alex's profile" })).toHaveAttribute('href', `/profiles/${profileFixture.id}`);
    expect(screen.queryByText('PRIVATE_DETAIL')).not.toBeInTheDocument();
  });

  it('shows a linked profile beside the saved checkpoint and the timeout that interrupted analysis', async () => {
    read.mockResolvedValue({ ...done, status: 'pending', error_type: 'ModelCallTimeoutError', progress: {
      processed_units: 300, total_units: 679, staged_count: 33, saved_count: 0, attempts: 2, next_attempt_at: '2026-10-30T23:20:54Z',
    } });
    renderWithProviders(<MeetingProfiles meetingId="meeting-id" />);
    expect(await screen.findByRole('link', { name: "View Alex's profile" })).toBeVisible();
    expect(screen.getByRole('progressbar', { name: 'Profile analysis progress' })).toHaveValue(300);
    expect(screen.getByText('300 of 679 transcript sections analyzed')).toBeVisible();
    expect(screen.getByText('33 candidates saved · 0 profiles updated')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('The last attempt timed out. Saved progress is kept.');
    expect(screen.getByText(/Next eligible attempt/)).toBeVisible();
    expect(screen.queryByText(/0 of \?/)).not.toBeInTheDocument();
    expect(retry).not.toHaveBeenCalled();
  });

  it('does not invent an analysis denominator or expose private errors when totals are unknown', async () => {
    read.mockResolvedValue({ ...done, status: 'failed', error_type: 'PRIVATE_DETAIL', progress: {
      processed_units: 0, total_units: null, staged_count: 0, saved_count: 0, attempts: 3, next_attempt_at: null,
    } });
    renderWithProviders(<MeetingProfiles meetingId="meeting-id" />);
    await screen.findByRole('link', { name: "View Alex's profile" });
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('The last attempt could not finish. Saved progress is kept. Retry this stage to continue.');
    expect(screen.queryByText('PRIVATE_DETAIL')).not.toBeInTheDocument();
  });

  it('requires fresh context after an invalidated manual request instead of promising a checkpoint retry', async () => {
    read.mockResolvedValue({ ...done, status: 'failed', error_type: 'ManualAnalysisInputChanged' });
    renderWithProviders(<MeetingProfiles meetingId="meeting-id" />);
    await screen.findByRole('link', { name: "View Alex's profile" });
    expect(screen.getByRole('status')).toHaveTextContent('Review the meeting and confirm a fresh analysis request.');
    expect(screen.getByRole('status')).not.toHaveTextContent('Retry this stage');
    expect(screen.getByRole('status')).not.toHaveTextContent('Saved progress is kept');
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
    expect(await screen.findByRole('link', { name: "View Alex's profile" })).toBeInTheDocument();
  });
});
