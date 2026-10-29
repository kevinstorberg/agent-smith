import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import type { MeetingParticipants as Participants, ProfileSummary } from '../../api';
import { POLL_INTERVAL_MS } from '../../constants';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { MeetingParticipants } from '../MeetingParticipants';

vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { meetings: { participants: vi.fn(), updateParticipants: vi.fn(), process: vi.fn() }, profiles: { list: vi.fn() } } };
});
import { api, ApiError } from '../../api';

const read = vi.mocked(api.meetings.participants);
const update = vi.mocked(api.meetings.updateParticipants);
const process = vi.mocked(api.meetings.process);
const changed = vi.fn();
const speakerKey = 'a'.repeat(64);
const empty: Participants = { revision: 0, items: [], provider_participants: [{ name: 'Provider Person', email: 'provider@example.test' }],
  speakers: [{ key: speakerKey, label: 'Speaker 1', segment_count: 12 }], running: false, enrolled: false };
const existing: ProfileSummary = { ...profileFixture, created_at: profileFixture.updated_at, claim_count: 2, meeting_count: 2 };

beforeEach(() => {
  vi.clearAllMocks();
  read.mockResolvedValue(empty);
  update.mockResolvedValue({ ...empty, revision: 1 });
  process.mockResolvedValue({ status: 'queued' });
  vi.mocked(api.profiles.list).mockResolvedValue({ items: [existing], total: 1 });
});
afterEach(() => vi.useRealTimers());

describe('MeetingParticipants', () => {
  it('shows speaker context and opens its explicit assignment with the group preselected', async () => {
    read.mockResolvedValue({ ...empty, speakers: [{ ...empty.speakers[0], source: 'microphone', attribution: 'me', sample: 'A useful recorded statement.' }] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Assign speaker' }));
    expect(screen.getByText('A useful recorded statement.')).toBeInTheDocument();
    expect(screen.getByText(/microphone · me/)).toBeInTheDocument();
    expect(screen.getByLabelText('Transcript speaker')).toHaveValue(speakerKey);
    expect(process).not.toHaveBeenCalled();
    await screen.findByRole('option', { name: 'Alex · alex@example.test' });
  });

  it('keeps the provider roster read-only and appends an explicit manual speaker assignment', async () => {
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    await screen.findByText(/Provider Person/);
    expect(screen.queryByRole('button', { name: 'Remove participant' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Add participant' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: ' Manual Person ' } });
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'manual@example.test' } });
    fireEvent.change(screen.getByLabelText('Transcript speaker'), { target: { value: speakerKey } });
    fireEvent.submit(screen.getByRole('button', { name: 'Save participant' }).closest('form')!);
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 0,
      participants: [{ name: 'Manual Person', email: 'manual@example.test', speaker_key: speakerKey }] }));
    expect(changed).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Provider Person/)).toBeInTheDocument();
  });

  it('selects an existing canonical profile explicitly', async () => {
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add participant' }));
    await screen.findByRole('option', { name: 'Alex · alex@example.test' });
    fireEvent.change(screen.getByLabelText('Find an existing profile'), { target: { value: ' Alex ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Find profiles' }));
    await screen.findByRole('option', { name: 'Alex · alex@example.test' });
    expect(api.profiles.list).toHaveBeenCalledWith({ q: 'Alex', limit: 10 });
    fireEvent.change(screen.getByLabelText('Existing participant profile'), { target: { value: existing.id } });
    expect(screen.getByLabelText('Name')).toHaveValue('Alex');
    expect(screen.getByLabelText('Email')).toHaveValue('alex@example.test');
    expect(screen.getByRole('link', { name: 'Manage linked emails' })).toHaveAttribute('href', `/profiles/${existing.id}`);
    fireEvent.submit(screen.getByRole('button', { name: 'Save participant' }).closest('form')!);
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 0,
      participants: [{ name: 'Alex', email: 'alex@example.test', profile_id: existing.id }] }));
  });

  it('removes only the chosen manual person while retaining the others', async () => {
    read.mockResolvedValue({ ...empty, revision: 3, items: [{ name: 'Manual A' }, { name: 'Manual B' }] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    const person = (await screen.findByText('Manual A')).closest('li')!;
    fireEvent.click(within(person).getByRole('button', { name: 'Remove participant' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 3, participants: [{ name: 'Manual B' }] }));
  });

  it('disables participant edits and queueing while the meeting is active', async () => {
    read.mockResolvedValue({ ...empty, running: true, items: [{ name: 'Manual A' }] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    expect(await screen.findByRole('button', { name: 'Add participant' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Remove participant' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Assign speaker' })).toBeDisabled();
    expect(screen.getByText(/changes are available after processing finishes/)).toBeInTheDocument();
  });

  it('preserves a draft across409 and retries only with the refreshed roster revision', async () => {
    update.mockRejectedValueOnce(new ApiError('Participants changed.', 409));
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add participant' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'My manual draft' } });
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'draft@example.test' } });
    read.mockResolvedValue({ ...empty, revision: 2, items: [{ name: 'Added elsewhere' }] });
    fireEvent.submit(screen.getByRole('button', { name: 'Save participant' }).closest('form')!);
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('status')).toHaveTextContent('Review the latest participants before saving again.');
    expect(screen.getByLabelText('Name')).toHaveValue('My manual draft');
    fireEvent.submit(screen.getByRole('button', { name: 'Save participant' }).closest('form')!);
    await waitFor(() => expect(update).toHaveBeenLastCalledWith('meeting-id', { expected_revision: 2,
      participants: [{ name: 'Added elsewhere' }, { name: 'My manual draft', email: 'draft@example.test' }] }));
  });

  it('keeps a blocked draft and resumes its availability check after processing finishes', async () => {
    vi.useFakeTimers();
    update.mockRejectedValueOnce(new ApiError('This meeting is processing.', 409));
    await act(async () => { renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />); });
    fireEvent.click(screen.getByRole('button', { name: 'Add participant' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Saved draft' } });
    read.mockResolvedValue({ ...empty, running: true });
    await act(async () => { fireEvent.submit(screen.getByRole('button', { name: 'Save participant' }).closest('form')!); });
    expect(screen.getByText(/changes are available after processing finishes/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save participant' })).toBeDisabled();
    read.mockResolvedValue({ ...empty, revision: 1, running: false });
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); });
    expect(screen.getByRole('button', { name: 'Save participant' })).not.toBeDisabled();
    expect(screen.getByLabelText('Name')).toHaveValue('Saved draft');
  });

  it('clears multiple stale speaker keys atomically without removing the people', async () => {
    read.mockResolvedValue({ ...empty, revision: 2, items: [{ name: 'Manual A', speaker_key: 'stale-a' }, { name: 'Manual B', speaker_key: 'stale-b' }],
      stale_speaker_keys: ['stale-a', 'stale-b'] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Clear outdated assignments' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 2,
      participants: [{ name: 'Manual A', speaker_key: null }, { name: 'Manual B', speaker_key: null }] }));
  });

  it('shows a local reader error and retries without exposing private exception text', async () => {
    read.mockRejectedValueOnce(new Error('PRIVATE_READER_DETAIL'));
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load participants.');
    expect(screen.queryByText(/PRIVATE_READER_DETAIL/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText(/Provider Person/)).toBeInTheDocument();
  });
});
