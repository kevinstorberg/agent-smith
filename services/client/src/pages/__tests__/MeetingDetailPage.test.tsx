import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes, useLocation, useNavigate } from 'react-router';
import { renderWithProviders } from '../../test-utils';
import { POLL_INTERVAL_MS } from '../../constants';
import { MeetingDetailPage } from '../MeetingDetailPage';
import { meetingFixture } from './meetingFixture';
import type { MeetingProcessingState } from '../../api';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: {
  meetings: { get: vi.fn(), processing: vi.fn(), transcript: vi.fn(), deleteTranscript: vi.fn(), retryTranscript: vi.fn(), memories: vi.fn(), retryMemories: vi.fn(), profiles: vi.fn(), retryProfiles: vi.fn(), participants: vi.fn(), updateParticipants: vi.fn(), identifyParticipants: vi.fn(), process: vi.fn(), updateLabels: vi.fn(), suggestLabels: vi.fn() },
  profiles: { list: vi.fn() }, meetingAnalysis: { candidates: vi.fn(), request: vi.fn(), progress: vi.fn(), resume: vi.fn() },
} }));
import { api } from '../../api';
const progress = { processed_units: 0, total_units: null, staged_count: 0, saved_count: 0, attempts: 0, next_attempt_at: null };
const processing: MeetingProcessingState = { transcript: { status: 'not_imported', total: 0, error_type: null, captured_at: null }, speakers: { status: 'not_imported', error_type: null, progress }, memories: { status: 'not_imported', reason: null, error_type: null, progress }, profiles: { status: 'not_imported', reason: null, error_type: null, progress }, edit_lock_reason: null };
const MID = meetingFixture.id;
function Probe() {
  const location = useLocation(); const navigate = useNavigate();
  return <><output data-testid="location">{location.pathname}{location.search}{location.hash}</output><button onClick={() => navigate(-1)}>History back</button><button onClick={() => navigate('/meetings/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee')}>Other meeting</button></>;
}
function renderPage(suffix = '') { return renderWithProviders(<><Routes><Route path="/meetings/:id" element={<MeetingDetailPage />} /></Routes><Probe /></>, { initialEntries: [`/meetings/${MID}${suffix}`] }); }
const tab = (label: string) => fireEvent.click(within(screen.getByRole('navigation', { name: 'Meeting views' })).getByRole('link', { name: label }));
async function settle() { await act(async () => { await Promise.resolve(); await Promise.resolve(); }); }
const originalShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal');
beforeAll(() => Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true; } }));
afterAll(() => { if (originalShowModal) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', originalShowModal); else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal'); });
const scroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
beforeAll(() => Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() }));
afterAll(() => { if (scroll) Object.defineProperty(Element.prototype, 'scrollIntoView', scroll); else delete (Element.prototype as any).scrollIntoView; });
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.meetings.get).mockResolvedValue(meetingFixture);
  vi.mocked(api.meetings.processing).mockResolvedValue(structuredClone(processing));
  vi.mocked(api.meetings.transcript).mockResolvedValue({ status: 'ready', items: [{ id: 'segment-0', text: 'Saved statement', speaker: {}, start_time: null, end_time: null }], total: 1, limit: 100, offset: 0, error_type: null, captured_at: null });
  vi.mocked(api.meetings.memories).mockResolvedValue({ status: 'done', items: [{ id: 'memory', content: 'A reusable product decision.', kind: 'decision', evidence: [] }], reason: null, error_type: null, updated_at: null });
  vi.mocked(api.meetings.profiles).mockResolvedValue({ status: 'done', items: [{ id: 'profile', display_name: 'Alex', email: null, revision: 1 }], reason: null, error_type: null });
  vi.mocked(api.meetings.participants).mockResolvedValue({ revision: 0, items: [], people: [], unlinked_attendees: [], provider_participants: [], speakers: [], running: false, enrolled: false });
  vi.mocked(api.profiles.list).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.meetings.process).mockResolvedValue({ status: 'queued' });
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('MeetingDetailPage', () => {
  it('defaults to a readable Overview without loading or rendering the heavy views', async () => {
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Product planning' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('Ship the next release.')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Open original meeting' })).toHaveAttribute('href', meetingFixture.source_url);
    expect(api.meetings.processing).toHaveBeenCalledWith(MID);
    for (const read of [api.meetings.transcript, api.meetings.participants, api.meetings.memories, api.meetings.profiles]) expect(read).not.toHaveBeenCalled();
    expect(screen.queryByRole('region', { name: 'Meeting transcript' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText(/Meeting details ·/));
    expect(screen.getByText('granola')).toBeVisible();
  });

  it('fetches only the active heavy view, preserves URL query fields and supports history', async () => {
    renderPage('?q=kept'); await screen.findByText('Ship the next release.');
    tab('Memories'); expect(await screen.findByText('A reusable product decision.')).toBeVisible();
    expect(api.meetings.transcript).not.toHaveBeenCalled(); expect(api.meetings.profiles).not.toHaveBeenCalled();
    tab('Profiles'); expect(await screen.findByRole('link', { name: "View Alex's profile" })).toHaveAttribute('href', '/profiles/profile');
    expect(screen.queryByText('A reusable product decision.')).not.toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('q=kept&tab=profiles');
    fireEvent.click(screen.getByRole('button', { name: 'History back' }));
    expect(await screen.findByText('A reusable product decision.')).toBeVisible();
  });

  it.each([['#meeting-summary', 'Overview'], ['#meeting-participants', 'Transcript'], ['#meeting-transcript', 'Transcript'], ['#meeting-memories', 'Memories'], ['#meeting-profiles', 'Profiles']])('opens legacy %s in %s while retaining its hash and other query fields', async (hash, label) => {
    renderPage(`?tab=overview&kept=yes${hash}`);
    expect(await within(await screen.findByRole('navigation', { name: 'Meeting views' })).findByRole('link', { name: label })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTestId('location')).toHaveTextContent(hash);
    expect(screen.getByTestId('location')).toHaveTextContent('kept=yes');
  });

  it('loads one exact window for a later statement and offers the beginning without a prefix crawl', async () => {
    vi.mocked(api.meetings.transcript).mockImplementation(async (_id, params) => ({ status: 'ready', total: 900, offset: params?.offset || 0, limit: 100, error_type: null, captured_at: null, items: Array.from({ length: 100 }, (_, i) => ({ id: `segment-${(params?.offset || 0) + i}`, text: `Statement ${(params?.offset || 0) + i}`, speaker: {}, start_time: null, end_time: null })) }));
    renderPage('#transcript-segment-650');
    expect(await screen.findByText('Statement 650')).toBeVisible();
    expect(api.meetings.transcript).toHaveBeenCalledTimes(1);
    expect(api.meetings.transcript).toHaveBeenLastCalledWith(MID, { limit: 100, offset: 600 });
    fireEvent.click(screen.getByRole('button', { name: 'Load more transcript' }));
    await screen.findByText('Statement 799');
    expect(api.meetings.transcript).toHaveBeenLastCalledWith(MID, { limit: 100, offset: 700 });
    fireEvent.click(screen.getByRole('button', { name: 'Show beginning' }));
    await screen.findByText('Statement 0');
    expect(api.meetings.transcript).toHaveBeenLastCalledWith(MID, { limit: 100, offset: 0 });
  });

  it('keeps participant drafts and loaded transcript pages across tabs and failed summary refreshes', async () => {
    vi.useFakeTimers();
    vi.mocked(api.meetings.transcript).mockImplementation(async (_id, params) => ({ status: 'ready', total: 101, offset: params?.offset || 0, limit: 100, error_type: null, captured_at: null, items: Array.from({ length: params?.offset ? 1 : 100 }, (_, i) => ({ id: `segment-${(params?.offset || 0) + i}`, text: `Line ${(params?.offset || 0) + i}`, speaker: {}, start_time: null, end_time: null })) }));
    renderPage('?tab=transcript'); await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Load more transcript' })); await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Add participant' })); await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Name and email' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'My retained draft' } });
    tab('Memories'); await settle(); expect(screen.queryByText('Line 100')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    tab('Transcript'); await settle();
    expect(screen.getByLabelText('Name')).toHaveValue('My retained draft'); expect(screen.getByText('Line 100')).toBeVisible();
    vi.mocked(api.meetings.get).mockRejectedValue(new Error('Temporary failure'));
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); }); await settle();
    expect(screen.getByText(/Could not refresh this meeting/)).toBeVisible();
    expect(screen.getByLabelText('Name')).toHaveValue('My retained draft'); expect(screen.getByText('Line 100')).toBeVisible();
  });

  it('shows the beginning after a late statement assignment changes the active anchor', async () => {
    vi.mocked(api.meetings.transcript).mockImplementation(async (_id, params) => ({ status: 'ready', total: 900, offset: params?.offset || 0, limit: 100, error_type: null, captured_at: null, items: Array.from({ length: 100 }, (_, i) => ({ id: `segment-${(params?.offset || 0) + i}`, text: `Statement ${(params?.offset || 0) + i}`, speaker: {}, start_time: null, end_time: null })) }));
    renderPage('#transcript-segment-650');
    const statement = (await screen.findByText('Statement 650')).closest('article')!;
    fireEvent.click(within(statement).getByRole('button', { name: 'Assign this statement' }));
    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: 'Name and email' }));
    await screen.findByLabelText('Name');
    expect(screen.getByTestId('location')).toHaveTextContent('#meeting-participants');
    fireEvent.click(screen.getByRole('button', { name: 'Show beginning' }));
    expect(await screen.findByText('Statement 0')).toBeVisible();
    expect(document.getElementById('transcript-segment-650')).not.toBeInTheDocument();
    expect(api.meetings.transcript).toHaveBeenLastCalledWith(MID, { limit: 100, offset: 0 });
    expect(screen.getByLabelText('Name')).toBeInTheDocument();
  });

  it.each(['a'.repeat(64), null])('blocks assigning a displayed statement with an old or missing source stamp: %s', async transcriptHash => {
    vi.mocked(api.meetings.transcript).mockResolvedValue({ status: 'ready', total: 1, offset: 0, limit: 100, error_type: null, captured_at: null,
      transcript_hash: transcriptHash, items: [{ id: 'segment-0', text: 'Words from an older transcript', speaker: {}, start_time: null, end_time: null }],
    });
    vi.mocked(api.meetings.participants).mockResolvedValue({ revision: 3, items: [], people: [], unlinked_attendees: [], provider_participants: [], speakers: [], running: false, enrolled: true, transcript_hash: 'b'.repeat(64) });
    renderPage('?tab=transcript');
    await screen.findByText('Words from an older transcript');
    fireEvent.click(screen.getByRole('button', { name: 'Assign this statement' }));
    await screen.findByRole('dialog', { name: 'Assign statement' });
    fireEvent.click(screen.getByRole('button', { name: 'Name and email' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Casey' } });
    expect(screen.getByRole('button', { name: 'Assign statement' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('Cancel this draft and select a current statement');
    expect(api.meetings.updateParticipants).not.toHaveBeenCalled();
    vi.mocked(api.meetings.transcript).mockResolvedValue({ status: 'ready', total: 1, offset: 0, limit: 100, error_type: null, captured_at: null,
      transcript_hash: 'b'.repeat(64), items: [{ id: 'segment-0', text: 'Words from the current transcript', speaker: {}, start_time: null, end_time: null }],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reload transcript' }));
    await screen.findByText('Words from the current transcript');
    fireEvent.click(screen.getByRole('button', { name: 'Assign this statement' }));
    await screen.findByRole('dialog', { name: 'Assign statement' });
    fireEvent.click(screen.getByRole('button', { name: 'Name and email' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Casey' } });
    fireEvent.click(screen.getByRole('button', { name: 'Assign statement' }));
    await waitFor(() => expect(api.meetings.updateParticipants).toHaveBeenCalledWith(MID, { expected_revision: 3, expected_transcript_hash: 'b'.repeat(64), participants: [{ name: 'Casey', segment_id: 'segment-0' }] }));
  });

  it('reports a missing deep-linked statement without describing an existing transcript as empty', async () => {
    vi.mocked(api.meetings.transcript).mockResolvedValue({ status: 'ready', total: 708, offset: 9900, limit: 100, items: [], error_type: null, captured_at: null });
    renderPage('#transcript-segment-9999');
    expect(await screen.findByText('This statement is not available in the saved transcript.')).toBeVisible();
    expect(screen.queryByText('The saved transcript is empty.')).not.toBeInTheDocument();
    expect(screen.queryByText(/Showing statements/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show beginning' })).toBeEnabled();
    expect(api.meetings.transcript).toHaveBeenCalledTimes(1);
  });

  it('preserves a manual analysis receipt URL across tabs and reloads progress without submitting again', async () => {
    const request_id = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
    vi.mocked(api.meetings.processing).mockResolvedValue({ ...processing, transcript: { ...processing.transcript, status: 'ready' }, memories: { ...processing.memories, status: 'done' }, profiles: { ...processing.profiles, status: 'done' } });
    vi.mocked(api.meetingAnalysis.progress).mockResolvedValue({ request_id, scope: 'profiles', target_profile_id: null, status: 'done', items: [], created_at: '2026-10-30T12:00:00Z', updated_at: '2026-10-30T12:00:00Z' });
    renderPage(`?analysis=${request_id}`);
    await waitFor(() => expect(api.meetingAnalysis.progress).toHaveBeenCalledWith(request_id));
    tab('Memories'); await screen.findByText('A reusable product decision.');
    tab('Transcript'); await screen.findByText('Saved statement');
    expect(screen.getByTestId('location')).toHaveTextContent(`analysis=${request_id}&tab=transcript`);
    expect(api.meetingAnalysis.progress).toHaveBeenCalledTimes(1);
    expect(api.meetingAnalysis.request).not.toHaveBeenCalled();
  });

  it('stops hidden view polling and ignores its delayed payload until the view is active again', async () => {
    vi.useFakeTimers();
    let resolve!: (value: Awaited<ReturnType<typeof api.meetings.memories>>) => void;
    vi.mocked(api.meetings.memories).mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValue({ status: 'done', items: [], reason: null, error_type: null, updated_at: null });
    renderPage('?tab=memories'); await settle();
    tab('Overview'); await settle();
    await act(async () => { resolve({ status: 'failed', items: [], reason: null, error_type: 'Old', updated_at: null }); });
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2); }); await settle();
    expect(api.meetings.memories).toHaveBeenCalledTimes(1);
    tab('Memories'); await settle();
    expect(api.meetings.memories).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('button', { name: 'Retry memory generation' })).not.toBeInTheDocument();
  });

  it('queues processing from Overview without requesting inactive tab payloads', async () => {
    renderPage(); fireEvent.click(await screen.findByRole('button', { name: 'Process meeting' }));
    await waitFor(() => expect(api.meetings.process).toHaveBeenCalledWith(MID));
    await waitFor(() => expect(api.meetings.processing).toHaveBeenCalledTimes(2));
    expect(api.meetings.transcript).not.toHaveBeenCalled(); expect(api.meetings.memories).not.toHaveBeenCalled(); expect(api.meetings.profiles).not.toHaveBeenCalled();
  });

  it('makes a ready-transcript speaker failure visible without falsely calling unknown speakers a failure', async () => {
    vi.mocked(api.meetings.processing).mockResolvedValue({ ...processing, transcript: { ...processing.transcript, status: 'ready' }, speakers: { status: 'failed', error_type: 'SpeakerAnalysisError', progress } });
    renderPage(); await screen.findByText('Speakers: Needs attention');
    fireEvent.click(screen.getByText('Processing details'));
    expect(screen.getByText(/did not produce a valid saved result/)).toBeVisible();
    expect(screen.queryByText(/0 of \? statements reviewed/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Manage speaker assignments' })).toHaveAttribute('href', '#meeting-participants');
    expect(api.meetings.identifyParticipants).not.toHaveBeenCalled();
  });

  it('pauses compact polling after three failures and recovers only on explicit refresh', async () => {
    vi.useFakeTimers(); vi.mocked(api.meetings.processing).mockRejectedValue(new Error('Unavailable'));
    renderPage(); await settle();
    for (let i = 0; i < 3; i++) { await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); }); await settle(); }
    expect(api.meetings.processing).toHaveBeenCalledTimes(3);
    expect(screen.getByText(/Automatic refresh is paused/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh status' })); await settle();
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); }); await settle();
    expect(api.meetings.processing).toHaveBeenCalledTimes(4);
    expect(screen.getByText(/Automatic refresh is paused/)).toBeVisible();
    vi.mocked(api.meetings.processing).mockResolvedValue(processing);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh status' })); await settle();
    expect(screen.queryByText(/Automatic refresh is paused/)).not.toBeInTheDocument();
  });

  it('ignores a delayed old meeting summary after route identity changes', async () => {
    let resolve!: (value: typeof meetingFixture) => void;
    vi.mocked(api.meetings.get).mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValue({ ...meetingFixture, id: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee', title: 'Other meeting title' });
    renderPage(); fireEvent.click(screen.getByRole('button', { name: 'Other meeting' }));
    await screen.findByRole('heading', { name: 'Other meeting title' });
    await act(async () => resolve(meetingFixture));
    expect(screen.queryByRole('heading', { name: 'Product planning' })).not.toBeInTheDocument();
  });

  it.each(['javascript:alert(1)', 'data:text/html,<script>bad</script>', '/relative-path'])('keeps unsafe source URL unlinked: %s', async source_url => {
    vi.mocked(api.meetings.get).mockResolvedValue({ ...meetingFixture, source_url }); renderPage(); await screen.findByRole('heading', { name: 'Product planning' }); expect(screen.queryByRole('link', { name: 'Open original meeting' })).not.toBeInTheDocument();
  });
});
