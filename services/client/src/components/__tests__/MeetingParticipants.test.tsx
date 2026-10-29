import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import type { MeetingParticipants as Participants, ProfileSummary } from '../../api';
import { POLL_INTERVAL_MS } from '../../constants';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { MeetingParticipants } from '../MeetingParticipants';

vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { meetings: { participants: vi.fn(), updateParticipants: vi.fn(), process: vi.fn(), identifyParticipants: vi.fn() }, profiles: { list: vi.fn() } } };
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
    await screen.findByRole('option', { name: 'Alex · alex@example.test' });
    await waitFor(() => expect(api.profiles.list).toHaveBeenCalledWith({ q: 'Alex', limit: 10 }));
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

  it('allows assignments during unrelated memory work and explains a persona lock', async () => {
    read.mockResolvedValue({ ...empty, running: true, edit_lock_reason: null });
    const rendered = renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    expect(await screen.findByRole('button', { name: 'Assign speaker' })).toBeEnabled();
    rendered.unmount();
    read.mockResolvedValue({ ...empty, running: true, edit_lock_reason: 'analyzing_personas' });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    expect(await screen.findByRole('button', { name: 'Assign speaker' })).toBeDisabled();
    expect(screen.getByText(/current persona review finishes/)).toBeInTheDocument();
  });

  it('saves a single statement with its transcript hash without assigning the shared channel', async () => {
    read.mockResolvedValue({ ...empty, transcript_hash: 'b'.repeat(64), edit_lock_reason: null });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} statement={{ id: 'segment-2', text: 'My own statement.' }} />);
    await screen.findByLabelText('Name');
    expect(screen.queryByLabelText('Transcript speaker')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Casey' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save participant' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 0, expected_transcript_hash: 'b'.repeat(64),
      participants: [{ name: 'Casey', segment_id: 'segment-2' }] }));
  });

  it('preserves an unsaved participant draft when a different statement is selected', async () => {
    const busy = vi.fn();
    const view = renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} onBusyChange={busy} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add participant' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Unsaved person' } });
    view.rerender(<MeetingParticipants meetingId="meeting-id" onChanged={changed} onBusyChange={busy} statement={{ id: 'segment-7', text: 'Another statement' }} />);
    expect(screen.getByLabelText('Name')).toHaveValue('Unsaved person');
    expect(screen.getByLabelText('Transcript speaker')).toBeInTheDocument();
    expect(busy).toHaveBeenLastCalledWith(true);
    expect(update).not.toHaveBeenCalled();
  });

  it('keeps the submitted statement and fields while a save is in flight', async () => {
    let finish: (value: Participants) => void = () => undefined;
    update.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    read.mockResolvedValue({ ...empty, transcript_hash: 'b'.repeat(64) });
    const closed = vi.fn();
    const view = renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} onStatementClosed={closed}
      statement={{ id: 'segment-0', text: 'Original statement' }} />);
    fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'Original person' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save participant' }));
    view.rerender(<MeetingParticipants meetingId="meeting-id" onChanged={changed} onStatementClosed={closed}
      statement={{ id: 'segment-1', text: 'Different statement' }} />);
    expect(screen.getByLabelText('Name')).toHaveValue('Original person');
    expect(screen.getByText('Original statement')).toBeInTheDocument();
    expect(screen.queryByText('Different statement')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled();
    expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 0, expected_transcript_hash: 'b'.repeat(64),
      participants: [{ name: 'Original person', segment_id: 'segment-0' }] });
    await act(async () => { finish({ ...empty, revision: 1 }); });
    expect(closed).toHaveBeenCalledTimes(1);
  });

  it('includes the captured hash when removing another person while retaining a statement assignment', async () => {
    const statement = { name: 'Statement person', segment_id: 'segment-0' };
    read.mockResolvedValue({ ...empty, transcript_hash: 'b'.repeat(64), items: [statement, { name: 'Other attendee' }] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    const row = (await screen.findByText('Other attendee')).closest('li')!;
    fireEvent.click(within(row).getByRole('button', { name: 'Remove participant' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 0, expected_transcript_hash: 'b'.repeat(64), participants: [statement] }));
  });

  it('includes the captured hash when clearing stale channels while retaining statement assignments', async () => {
    const statement = { name: 'Statement person', segment_id: 'segment-0' };
    read.mockResolvedValue({ ...empty, transcript_hash: 'b'.repeat(64), items: [statement, { name: 'Old channel', speaker_key: 'stale-key' }], stale_speaker_keys: ['stale-key'] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Clear outdated assignments' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 0, expected_transcript_hash: 'b'.repeat(64),
      participants: [statement, { name: 'Old channel', speaker_key: null }] }));
  });

  it('clears stale statement assignments together after transcript deletion', async () => {
    read.mockResolvedValue({ ...empty, transcript_hash: null, items: [{ name: 'A', segment_id: 'segment-0' }, { name: 'B', segment_id: 'segment-1' }],
      stale_segment_ids: ['segment-0', 'segment-1'] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Clear outdated statement assignments' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 0,
      participants: [{ name: 'A', segment_id: null }, { name: 'B', segment_id: null }] }));
  });

  it('requires selecting a current statement if the transcript changed while saving', async () => {
    read.mockResolvedValue({ ...empty, transcript_hash: 'b'.repeat(64) });
    update.mockRejectedValueOnce(new ApiError('Transcript changed.', 409));
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed}
      statement={{ id: 'segment-0', text: 'Original transcript words' }} />);
    fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'My draft' } });
    read.mockResolvedValue({ ...empty, transcript_hash: 'c'.repeat(64) });
    fireEvent.click(screen.getByRole('button', { name: 'Save participant' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Cancel this draft and select a current statement');
    expect(screen.getByRole('button', { name: 'Save participant' })).toBeDisabled();
    expect(screen.getByLabelText('Name')).toHaveValue('My draft');
    expect(screen.getByText('Original transcript words')).toBeInTheDocument();
    expect(update).toHaveBeenCalledTimes(1);
  });
});
