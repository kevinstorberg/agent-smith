import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
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
const modal = () => screen.getByRole('dialog');
const chooseManual = () => fireEvent.click(within(modal()).getByRole('button', { name: 'Name and email' }));
const saveButton = () => within(modal()).getByRole('button', { name: /^(Add participant|Assign statement|Assign audio channel)$/ });
const originalShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal');
beforeAll(() => Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true; } }));
afterAll(() => { if (originalShowModal) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', originalShowModal); else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal'); });
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
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('MeetingParticipants', () => {
  it('renders one canonical person with all statement assignments and removes only the selected assignment', async () => {
    const first = { name: 'Alex Work', email: 'work@example.test', profile_id: existing.id, segment_id: 'segment-9' };
    const second = { name: 'Alex Personal', email: 'personal@example.test', profile_id: existing.id, segment_id: 'segment-25' };
    read.mockResolvedValue({ ...empty, revision: 7, transcript_hash: 'b'.repeat(64), items: [first, second],
      provider_participants: [{ name: 'Duplicate raw provider', email: 'personal@example.test' }], unlinked_attendees: [],
      people: [{ key: `profile:${existing.id}`, profile_id: existing.id, display_name: 'Alex', names: ['Alex', 'Alex Work', 'Alex Personal'], emails: ['work@example.test', 'personal@example.test'], sources: ['provider', 'manual'], assignments: [first, second] }] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    const person = (await screen.findByText('Alex')).closest('li')!;
    expect(screen.getAllByText('Alex')).toHaveLength(1);
    expect(screen.queryByText('Duplicate raw provider')).not.toBeInTheDocument();
    expect(within(person).getByRole('link', { name: 'View profile' })).toHaveAttribute('href', `/profiles/${existing.id}`);
    expect(within(person).getByText('2 assignments')).toBeInTheDocument();
    fireEvent.click(within(person).getByText('2 assignments'));
    const row = within(person).getByRole('link', { name: 'Statement segment-9' }).closest('li')!;
    fireEvent.click(within(row).getByRole('button', { name: 'Remove assignment' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 7, expected_transcript_hash: 'b'.repeat(64), participants: [second] }));
  });

  it('keeps same-named unlinked people distinct and labels shared audio channels honestly', async () => {
    const one = { name: 'Jordan', segment_id: 'segment-1' };
    const two = { name: 'Jordan', segment_id: 'segment-2' };
    read.mockResolvedValue({ ...empty, items: [one, two], people: [one, two].map(person => ({ key: `statement:${person.segment_id}`, display_name: 'Jordan', profile_id: null, emails: [], names: ['Jordan'], sources: ['manual'], assignments: [person] })), unlinked_attendees: [] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    expect(await screen.findAllByText('Jordan')).toHaveLength(2);
    fireEvent.click(screen.getByText('Audio channels (1)'));
    expect(screen.getByText(/A shared channel can contain several people/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Assign speaker' })).toBeEnabled();
  });

  it('keeps distinct raw roster aliases in one canonical person without duplicate row keys', async () => {
    const first = { name: 'Alex Former', email: 'former@example.test', profile_id: 'old-profile' };
    const second = { name: 'Alex', email: 'current@example.test', profile_id: existing.id };
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      read.mockResolvedValue({ ...empty, items: [first, second], people: [{ key: `profile:${existing.id}`, profile_id: existing.id, display_name: 'Alex', emails: [], sources: ['manual'], assignments: [first, second] }], unlinked_attendees: [] });
      renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
      fireEvent.click(await screen.findByText('2 assignments'));
      expect(screen.getAllByText('Meeting participant')).toHaveLength(2);
      expect(errors.mock.calls.some(([message]) => String(message).includes('same key'))).toBe(false);
      fireEvent.click(screen.getAllByRole('button', { name: 'Remove assignment' })[0]);
      await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 0, participants: [second] }));
    } finally { errors.mockRestore(); }
  });

  it('shows speaker context and opens its explicit assignment with the group preselected', async () => {
    read.mockResolvedValue({ ...empty, speakers: [{ ...empty.speakers[0], source: 'microphone', attribution: 'me', sample: 'A useful recorded statement.' }] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Assign speaker' }));
    expect(screen.getByText('A useful recorded statement.')).toBeInTheDocument();
    expect(screen.getByText(/microphone · me/)).toBeInTheDocument();
    expect(within(modal()).getByText('Assign every statement in Speaker 1 to one person.')).toBeInTheDocument();
    expect(process).not.toHaveBeenCalled();
    await screen.findByRole('option', { name: 'Alex · alex@example.test' });
  });

  it('keeps the provider roster read-only and appends an explicit manual speaker assignment', async () => {
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    await screen.findByText(/Provider Person/);
    expect(screen.queryByRole('button', { name: 'Remove assignment' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Audio channels (1)'));
    fireEvent.click(screen.getByRole('button', { name: 'Assign speaker' }));
    chooseManual();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: ' Manual Person ' } });
    fireEvent.change(screen.getByLabelText('Email (optional)'), { target: { value: 'manual@example.test' } });
    fireEvent.submit(saveButton().closest('form')!);
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
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Email (optional)')).not.toBeInTheDocument();
    expect(within(modal()).getByText('alex@example.test')).toBeInTheDocument();
    expect(within(modal()).getByRole('link', { name: 'View profile' })).toHaveAttribute('href', `/profiles/${existing.id}`);
    fireEvent.submit(saveButton().closest('form')!);
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 0,
      participants: [{ name: 'Alex', email: 'alex@example.test', profile_id: existing.id }] }));
  });

  it('defaults to known profiles, requires a selection, and does not reset the current mode', async () => {
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add participant' }));
    expect(within(modal()).getByRole('button', { name: 'Existing profile' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Transcript speaker')).not.toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    fireEvent.submit(saveButton().closest('form')!);
    expect(update).not.toHaveBeenCalled();
    await screen.findByRole('option', { name: 'Alex · alex@example.test' });
    fireEvent.change(screen.getByLabelText('Existing participant profile'), { target: { value: existing.id } });
    fireEvent.click(within(modal()).getByRole('button', { name: 'Existing profile' }));
    expect(screen.getByLabelText('Existing participant profile')).toHaveValue(existing.id);
    expect(saveButton()).toBeEnabled();
    chooseManual();
    expect(screen.getByLabelText('Name')).toHaveValue('Alex');
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'A different person' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 0,
      participants: [{ name: 'A different person', email: 'alex@example.test' }] }));
  });

  it('cancels the dialog without writes and restores its trigger focus', async () => {
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    const add = await screen.findByRole('button', { name: 'Add participant' });
    add.focus(); fireEvent.click(add);
    expect(screen.getByLabelText('Find an existing profile')).toHaveFocus();
    chooseManual();
    expect(screen.getByLabelText('Name')).toHaveFocus();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Discarded draft' } });
    fireEvent(modal(), new Event('cancel', { cancelable: true }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(add).toHaveFocus();
    expect(update).not.toHaveBeenCalled();
  });

  it('retains the dialog on Escape and prevents edits while a save is pending', async () => {
    let finish: (value: Participants) => void = () => undefined;
    update.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add participant' })); chooseManual();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Saved person' } });
    fireEvent.click(saveButton());
    fireEvent(modal(), new Event('cancel', { cancelable: true }));
    expect(screen.getByLabelText('Name')).toBeDisabled();
    expect(screen.getByLabelText('Name')).toHaveValue('Saved person');
    expect(within(modal()).getByRole('button', { name: 'Cancel' })).toBeDisabled();
    expect(within(modal()).getByRole('button', { name: 'Existing profile' })).toBeDisabled();
    expect(update).toHaveBeenCalledTimes(1);
    await act(async () => finish({ ...empty, revision: 1 }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps an unknown-total legacy receipt readable and identifies only after confirmation', async () => {
    const result: Participants = { ...empty, attribution: { status: 'legacy', error_type: null,
      progress: { processed_units: 0, total_units: null, saved_count: 0, staged_count: 0, attempts: 0, next_attempt_at: null } } };
    read.mockResolvedValue(result);
    vi.mocked(api.meetings.identifyParticipants).mockResolvedValue({ status: 'queued' });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    const identify = await screen.findByRole('button', { name: 'Identify speakers' });
    expect(screen.getByText('Not reviewed.')).toBeInTheDocument();
    expect(screen.queryByText(/0 of \?/)).not.toBeInTheDocument();
    fireEvent.click(identify);
    expect(api.meetings.identifyParticipants).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    read.mockResolvedValue({ ...result, attribution: { ...result.attribution!, status: 'pending' } });
    fireEvent.click(identify);
    await waitFor(() => expect(api.meetings.identifyParticipants).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Identify speakers' })).toBeDisabled());
    expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('next meeting job run'));
    expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('Saved memories are kept'));
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it.each(['pending', 'running'] as const)('does not reset an already %s identification checkpoint', async status => {
    read.mockResolvedValue({ ...empty, attribution: { status, error_type: null,
      progress: { processed_units: 4, total_units: 12, saved_count: 2, staged_count: 2, attempts: 1, next_attempt_at: null } } });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    const identify = await screen.findByRole('button', { name: 'Identify speakers' });
    expect(identify).toBeDisabled(); fireEvent.click(identify);
    expect(confirm).not.toHaveBeenCalled(); expect(api.meetings.identifyParticipants).not.toHaveBeenCalled();
    expect(screen.getByText(status === 'pending' ? 'Queued for the next meeting job run.' : 'Reviewing 4 of 12 statements.')).toBeInTheDocument();
  });

  it.each(['done', 'failed'] as const)('clears a local queued state when the first refreshed receipt is already %s', async status => {
    const attribution: NonNullable<Participants['attribution']> = { status: 'legacy', error_type: null,
      progress: { processed_units: 0, total_units: null, saved_count: 0, staged_count: 0, attempts: 0, next_attempt_at: null } };
    read.mockResolvedValueOnce({ ...empty, attribution }).mockResolvedValue({ ...empty, attribution: { ...attribution, status, error_type: status === 'failed' ? 'SpeakerAnalysisError' : null } });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(api.meetings.identifyParticipants).mockResolvedValue({ status: 'queued' });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Identify speakers' }));
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Identify speakers' })).toBeEnabled());
    expect(screen.queryByText('Queued for the next meeting job run.')).not.toBeInTheDocument();
    expect(screen.queryByText(/0 of \?/)).not.toBeInTheDocument();
    expect(update).not.toHaveBeenCalled(); expect(api.meetings.identifyParticipants).toHaveBeenCalledTimes(1);
  });

  it('removes only the chosen manual person while retaining the others', async () => {
    read.mockResolvedValue({ ...empty, revision: 3, items: [{ name: 'Manual A' }, { name: 'Manual B' }] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    const person = (await screen.findByText('Manual A')).closest('li')!;
    fireEvent.click(within(person).getByRole('button', { name: 'Remove assignment' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 3, participants: [{ name: 'Manual B' }] }));
  });

  it('disables participant edits and queueing while the meeting is active', async () => {
    read.mockResolvedValue({ ...empty, running: true, items: [{ name: 'Manual A' }] });
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    expect(await screen.findByRole('button', { name: 'Add participant' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Remove assignment' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Assign speaker' })).toBeDisabled();
    expect(screen.getByText(/changes are available after processing finishes/)).toBeInTheDocument();
  });

  it('preserves a draft across409 and retries only with the refreshed roster revision', async () => {
    update.mockRejectedValueOnce(new ApiError('Participants changed.', 409));
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add participant' }));
    chooseManual();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'My manual draft' } });
    fireEvent.change(screen.getByLabelText('Email (optional)'), { target: { value: 'draft@example.test' } });
    read.mockResolvedValue({ ...empty, revision: 2, items: [{ name: 'Added elsewhere' }] });
    fireEvent.submit(saveButton().closest('form')!);
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('status')).toHaveTextContent('Review the latest participants before saving again.');
    expect(screen.getByLabelText('Name')).toHaveValue('My manual draft');
    fireEvent.submit(saveButton().closest('form')!);
    await waitFor(() => expect(update).toHaveBeenLastCalledWith('meeting-id', { expected_revision: 2,
      participants: [{ name: 'Added elsewhere' }, { name: 'My manual draft', email: 'draft@example.test' }] }));
  });

  it('retains a conflicted draft when its required reread fails and provides an explicit reread retry', async () => {
    update.mockRejectedValueOnce(new ApiError('Participants changed.', 409));
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add participant' }));
    chooseManual();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Retained draft' } });
    read.mockRejectedValueOnce(new Error('Unavailable'));
    fireEvent.click(saveButton());
    await screen.findByRole('button', { name: 'Refresh participants' });
    expect(saveButton()).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled();
    expect(screen.getByLabelText('Name')).toHaveValue('Retained draft');
    read.mockResolvedValue({ ...empty, revision: 8 });
    fireEvent.click(screen.getByRole('button', { name: 'Refresh participants' }));
    await waitFor(() => expect(saveButton()).toBeEnabled());
    fireEvent.click(saveButton());
    await waitFor(() => expect(update).toHaveBeenLastCalledWith('meeting-id', { expected_revision: 8, participants: [{ name: 'Retained draft' }] }));
  });

  it('keeps a blocked draft and resumes its availability check after processing finishes', async () => {
    vi.useFakeTimers();
    update.mockRejectedValueOnce(new ApiError('This meeting is processing.', 409));
    await act(async () => { renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} />); });
    fireEvent.click(screen.getByRole('button', { name: 'Add participant' }));
    chooseManual();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Saved draft' } });
    read.mockResolvedValue({ ...empty, running: true });
    await act(async () => { fireEvent.submit(saveButton().closest('form')!); });
    expect(screen.getByText(/changes are available after processing finishes/)).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    read.mockResolvedValue({ ...empty, revision: 1, running: false });
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); });
    expect(saveButton()).not.toBeDisabled();
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
    renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} statement={{ id: 'segment-2', text: 'My own statement.', transcriptHash: 'b'.repeat(64) }} />);
    await screen.findByRole('dialog'); chooseManual();
    await screen.findByLabelText('Name');
    expect(screen.queryByLabelText('Transcript speaker')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Casey' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(update).toHaveBeenCalledWith('meeting-id', { expected_revision: 0, expected_transcript_hash: 'b'.repeat(64),
      participants: [{ name: 'Casey', segment_id: 'segment-2' }] }));
  });

  it('preserves an unsaved participant draft when a different statement is selected', async () => {
    const busy = vi.fn();
    const view = renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} onBusyChange={busy} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add participant' }));
    chooseManual();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Unsaved person' } });
    view.rerender(<MeetingParticipants meetingId="meeting-id" onChanged={changed} onBusyChange={busy} statement={{ id: 'segment-7', text: 'Another statement', transcriptHash: 'b'.repeat(64) }} />);
    expect(screen.getByLabelText('Name')).toHaveValue('Unsaved person');
    expect(screen.queryByLabelText('Transcript speaker')).not.toBeInTheDocument();
    expect(busy).toHaveBeenLastCalledWith(true);
    expect(update).not.toHaveBeenCalled();
  });

  it('keeps the submitted statement and fields while a save is in flight', async () => {
    let finish: (value: Participants) => void = () => undefined;
    update.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    read.mockResolvedValue({ ...empty, transcript_hash: 'b'.repeat(64) });
    const closed = vi.fn();
    const view = renderWithProviders(<MeetingParticipants meetingId="meeting-id" onChanged={changed} onStatementClosed={closed}
      statement={{ id: 'segment-0', text: 'Original statement', transcriptHash: 'b'.repeat(64) }} />);
    await screen.findByRole('dialog'); chooseManual();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Original person' } });
    fireEvent.click(saveButton());
    view.rerender(<MeetingParticipants meetingId="meeting-id" onChanged={changed} onStatementClosed={closed}
      statement={{ id: 'segment-1', text: 'Different statement', transcriptHash: 'b'.repeat(64) }} />);
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
    fireEvent.click(within(row).getByRole('button', { name: 'Remove assignment' }));
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
      statement={{ id: 'segment-0', text: 'Original transcript words', transcriptHash: 'b'.repeat(64) }} />);
    await screen.findByRole('dialog'); chooseManual();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'My draft' } });
    read.mockResolvedValue({ ...empty, transcript_hash: 'c'.repeat(64) });
    fireEvent.click(saveButton());
    expect(await screen.findByRole('alert')).toHaveTextContent('Cancel this draft and select a current statement');
    expect(saveButton()).toBeDisabled();
    expect(screen.getByLabelText('Name')).toHaveValue('My draft');
    expect(screen.getByText('Original transcript words')).toBeInTheDocument();
    expect(update).toHaveBeenCalledTimes(1);
  });
});
