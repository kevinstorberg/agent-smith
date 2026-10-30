import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { useLocation, useNavigate } from 'react-router';
import { afterAll, afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../api';
import type { MeetingAnalysisCandidate, MeetingAnalysisReceipt } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { ManualMeetingAnalysis } from '../ManualMeetingAnalysis';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: {
  meetingAnalysis: { candidates: vi.fn(), request: vi.fn(), progress: vi.fn(), resume: vi.fn() },
} }));
const PID = 'b1bb54a0-60ec-44f8-a9ec-82e3456ee637';
const MID = '9d85d0c6-bf5d-41b9-9a7d-c1e082180b8e';
const RID = 'a3b8c4d5-e678-4567-89ab-cdef01234567';
const profile = { id: PID, display_name: 'Alex' };
const progress = { processed_units: 0, total_units: 100, staged_count: 0, saved_count: 0, attempts: 0, next_attempt_at: null };
const candidate: MeetingAnalysisCandidate = {
  id: MID, title: 'Roadmap discussion', source_name: 'work', meeting_start: '2026-10-28T12:00:00Z', labels: ['product'],
  match_reasons: ['identified_speaker'], attribution_ready: true,
  expected: { provider: 'granola', account_key: 'account', source_name: 'work', meeting_revision: 3, transcript_hash: 'a'.repeat(64), participants_revision: 2, speaker_updated_at: '2026-10-28T12:00:00Z', profile_updated_at: '2026-10-28T12:05:00Z', memory_updated_at: '2026-10-28T12:06:00Z' },
  stages: {
    profile: { status: 'done', can_reanalyze: true, blocked_reason: null, progress, job_id: 42, job_name: 'Personas' },
    memory: { status: 'done', can_reanalyze: true, blocked_reason: null, progress, job_id: 43, job_name: 'Meetings' },
  },
};
function receipt(status: MeetingAnalysisReceipt['status'] = 'queued'): MeetingAnalysisReceipt {
  return { request_id: RID, scope: 'profiles', target_profile_id: PID, created_at: '2026-10-30T12:00:00Z', updated_at: '2026-10-30T12:00:00Z', status,
    items: [{ meeting_id: MID, title: candidate.title, stages: { profile: { status, error_type: null, progress, job_id: 42, job_name: 'Personas' } } }] };
}
const changed = vi.fn();
function Navigation() {
  const location = useLocation(); const navigate = useNavigate();
  return <><output data-testid="location">{location.search}</output><button onClick={() => navigate('?analysis=b3b8c4d5-e678-4567-89ab-cdef01234567')}>Other receipt</button><button onClick={() => navigate('?tab=evidence&category=driver')}>Evidence tab</button></>;
}
function renderReview(options: { meeting?: boolean; initial?: string } = {}) {
  return renderWithProviders(<><ManualMeetingAnalysis {...options.meeting ? { meetingId: MID } : { profile }} onChanged={changed} /><Navigation /></>, { initialEntries: [options.initial || '/profiles/alex?tab=overview'] });
}
async function open() { fireEvent.click(screen.getByRole('button', { name: /Review past meetings|Reanalyze completed|View analysis progress/ })); return screen.findByRole('dialog'); }
async function selectAndReview() {
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Select Roadmap discussion' }));
  fireEvent.click(screen.getByRole('button', { name: 'Review selection' }));
}
async function settle() { await act(async () => { await Promise.resolve(); await Promise.resolve(); }); }
const showModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal');
beforeAll(() => Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute('open', ''); } }));
afterAll(() => { if (showModal) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', showModal); else delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).showModal; });
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.meetingAnalysis.candidates).mockReset().mockResolvedValue({ items: [structuredClone(candidate)], total: 1, profile: { ...profile, revision: 7 } });
  vi.mocked(api.meetingAnalysis.request).mockReset().mockImplementation(async input => ({ ...receipt(), request_id: input.request_id }));
  vi.mocked(api.meetingAnalysis.progress).mockReset().mockImplementation(async id => ({ ...receipt(), request_id: id }));
  vi.mocked(api.meetingAnalysis.resume).mockReset().mockResolvedValue(receipt('continued'));
});
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

it('loads candidates only on opening and confirms exact meetings, source values and target revision', async () => {
  renderReview();
  expect(api.meetingAnalysis.candidates).not.toHaveBeenCalled();
  await open(); await selectAndReview();
  expect(screen.getByRole('region', { name: 'Confirm meeting analysis' })).toHaveTextContent('Profiles for Alex');
  expect(screen.getByText(/normal generation costs/)).toBeVisible();
  expect(api.meetingAnalysis.request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm analysis' }));
  await waitFor(() => expect(api.meetingAnalysis.request).toHaveBeenCalledTimes(1));
  const input = vi.mocked(api.meetingAnalysis.request).mock.calls[0][0];
  expect(input).toEqual({ request_id: expect.any(String), confirmed: true, scope: 'profiles', target_profile: { id: PID, expected_revision: 7 }, meetings: [{ id: MID, expected: candidate.expected }] });
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(`analysis=${input.request_id}`));
  expect(screen.getByTestId('location')).toHaveTextContent('tab=overview');
  expect(screen.getByText(/Closing this view will not stop/)).toBeVisible();
});

it('keeps explicit selection across server pages and only sends selected IDs', async () => {
  const next = { ...candidate, id: 'ad85d0c6-bf5d-41b9-9a7d-c1e082180b8e', title: 'Security review' };
  vi.mocked(api.meetingAnalysis.candidates).mockImplementation(async params => ({ items: params.offset ? [next] : [candidate], total: 11, profile: { ...profile, revision: 7 } }));
  renderReview(); await open();
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Select Roadmap discussion' }));
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Select Security review' }));
  expect(screen.getByText('2 of 10 selected')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Review selection' }));
  const confirmation = screen.getByRole('region', { name: 'Confirm meeting analysis' });
  expect(within(confirmation).getAllByRole('listitem')).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm analysis' }));
  expect(vi.mocked(api.meetingAnalysis.request).mock.calls[0][0].meetings.map(item => item.id)).toEqual([MID, next.id]);
  expect(api.meetingAnalysis.candidates).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 10, offset: 10 }));
  await settle();
});

it('caps selection at ten explicit meetings and never expands it to all search results', async () => {
  const items = Array.from({ length: 12 }, (_, index) => ({ ...candidate, id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`, title: `Meeting ${index + 1}` }));
  vi.mocked(api.meetingAnalysis.candidates).mockImplementation(async params => ({ items: items.slice(params.offset || 0, (params.offset || 0) + 10), total: items.length, profile: { ...profile, revision: 7 } }));
  renderReview(); await open(); await screen.findByRole('checkbox', { name: 'Select Meeting 1' });
  for (let index = 1; index <= 10; index++) fireEvent.click(screen.getByRole('checkbox', { name: `Select Meeting ${index}` }));
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  expect(await screen.findByRole('checkbox', { name: 'Select Meeting 11' })).toBeDisabled();
  expect(screen.getByText('10 of 10 selected')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Review selection' }));
  expect(screen.getAllByRole('listitem')).toHaveLength(10);
});

it('separates target-only profiles from full-meeting memories when both outputs are selected', async () => {
  renderReview(); await open(); await screen.findByRole('checkbox', { name: 'Select Roadmap discussion' });
  fireEvent.change(screen.getByRole('combobox', { name: 'Analyze' }), { target: { value: 'both' } });
  expect(screen.getByText('Profiles update only Alex. Memories capture useful information from each full meeting.')).toBeVisible();
  await selectAndReview();
  expect(screen.getByRole('region', { name: 'Confirm meeting analysis' })).toHaveTextContent('Profiles for Alex · Memories from the full meetings');
});

it('automatically debounces search, resets paging and offers All saved meetings without authorizing anything', async () => {
  vi.useFakeTimers(); renderReview();
  fireEvent.click(screen.getByRole('button', { name: 'Review past meetings' })); await settle();
  fireEvent.change(screen.getByRole('textbox', { name: 'Search meetings' }), { target: { value: 'security' } });
  expect(api.meetingAnalysis.candidates).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(299); });
  expect(api.meetingAnalysis.candidates).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); }); await settle();
  expect(api.meetingAnalysis.candidates).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'security', offset: 0 }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Include saved transcript text in search' })); await settle();
  fireEvent.click(screen.getByRole('button', { name: 'All saved meetings' })); await settle();
  expect(api.meetingAnalysis.candidates).toHaveBeenLastCalledWith(expect.objectContaining({ related: false, search_transcript: true }));
  expect(api.meetingAnalysis.request).not.toHaveBeenCalled();
});

it('sends timezone-aware inclusive local-day boundaries and refuses reversed dates', async () => {
  renderReview(); await open(); await screen.findByRole('checkbox', { name: 'Select Roadmap discussion' });
  fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-10-28' } });
  fireEvent.change(screen.getByLabelText('Through'), { target: { value: '2026-10-29' } });
  await waitFor(() => expect(api.meetingAnalysis.candidates).toHaveBeenLastCalledWith(expect.objectContaining({
    after: new Date(2026, 9, 28, 0, 0, 0, 0).toISOString(), before: new Date(2026, 9, 29, 23, 59, 59, 999).toISOString(),
  })));
  const calls = vi.mocked(api.meetingAnalysis.candidates).mock.calls.length;
  fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-10-30' } });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Review selection' })).toBeDisabled());
  expect(api.meetingAnalysis.candidates).toHaveBeenCalledTimes(calls);
});

it('shows missing attribution and unfinished work as actionable blocked candidates', async () => {
  const blocked = { ...candidate, attribution_ready: false, stages: { ...candidate.stages,
    profile: { ...candidate.stages.profile, can_reanalyze: false, blocked_reason: 'Assign this profile to its transcript statements or speaker before requesting analysis.' } } };
  vi.mocked(api.meetingAnalysis.candidates).mockResolvedValue({ items: [blocked], total: 1, profile: { ...profile, revision: 7 } });
  renderReview(); await open();
  expect(await screen.findByRole('checkbox', { name: 'Select Roadmap discussion' })).toBeDisabled();
  expect(screen.getByText(/Assign this profile to its transcript statements/)).toBeVisible();
  expect(screen.getByRole('link', { name: 'Assign transcript speakers' })).toHaveAttribute('href', `/meetings/${MID}#meeting-participants`);
  expect(screen.getByRole('button', { name: 'Review selection' })).toBeDisabled();
});

it('offers All saved meetings when a zero-evidence profile has no related candidates', async () => {
  vi.mocked(api.meetingAnalysis.candidates).mockImplementation(async params => ({ items: params.related ? [] : [candidate], total: params.related ? 0 : 1, profile: { ...profile, revision: 7 } }));
  renderReview(); await open();
  expect(await screen.findByText(/Try All saved meetings/)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'All saved meetings' }));
  expect(await screen.findByRole('checkbox', { name: 'Select Roadmap discussion' })).toBeEnabled();
  expect(api.meetingAnalysis.request).not.toHaveBeenCalled();
});

it('uses server eligibility for a fresh profile review after source-changed unpublished work', async () => {
  const recoverable = { ...candidate, stages: { ...candidate.stages, profile: { ...candidate.stages.profile, status: 'failed', can_reanalyze: true } } };
  vi.mocked(api.meetingAnalysis.candidates).mockResolvedValue({ items: [recoverable], total: 1, profile: { ...profile, revision: 7 } });
  renderReview(); await open(); await selectAndReview();
  expect(screen.getByRole('button', { name: 'Confirm analysis' })).toBeEnabled();
  expect(api.meetingAnalysis.request).not.toHaveBeenCalled();
});

it('preselects the exact meeting on its detail view and allows a memory-only scope without a target profile', async () => {
  vi.mocked(api.meetingAnalysis.candidates).mockResolvedValue({ items: [candidate], total: 1, profile: null });
  renderReview({ meeting: true }); await open();
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Select Roadmap discussion' })).toBeChecked());
  expect(api.meetingAnalysis.candidates).toHaveBeenCalledWith(expect.objectContaining({ meeting_id: MID, related: false }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Analyze' }), { target: { value: 'memories' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review selection' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm analysis' }));
  const input = vi.mocked(api.meetingAnalysis.request).mock.calls[0][0];
  expect(input.scope).toBe('memories'); expect(input).not.toHaveProperty('target_profile');
  await settle();
});

it('retains the same UUID and frozen payload after an uncertain response, including closing and reopening', async () => {
  vi.mocked(api.meetingAnalysis.request).mockRejectedValueOnce(new Error('Lost receipt'));
  renderReview(); await open(); await selectAndReview();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm analysis' }));
  await screen.findByRole('button', { name: 'Retry same request' });
  const original = structuredClone(vi.mocked(api.meetingAnalysis.request).mock.calls[0][0]);
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await open(); fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }));
  await waitFor(() => expect(api.meetingAnalysis.request).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.meetingAnalysis.request).mock.calls[1][0]).toEqual(original);
  expect(screen.queryByRole('button', { name: 'Confirm analysis' })).not.toBeInTheDocument();
});

it('requires a fresh selection and explicit confirmation after a stale source conflict', async () => {
  vi.mocked(api.meetingAnalysis.request).mockRejectedValueOnce(new ApiError('Speaker assignments changed.', 409));
  renderReview(); await open(); await selectAndReview(); fireEvent.click(screen.getByRole('button', { name: 'Confirm analysis' }));
  await waitFor(() => expect(screen.getByText(/Speaker assignments changed/)).toBeVisible());
  expect(await screen.findByRole('checkbox', { name: 'Select Roadmap discussion' })).not.toBeChecked();
  expect(screen.getByRole('button', { name: 'Review selection' })).toBeDisabled();
  expect(api.meetingAnalysis.request).toHaveBeenCalledTimes(1);
  await selectAndReview(); fireEvent.click(screen.getByRole('button', { name: 'Confirm analysis' }));
  const calls = vi.mocked(api.meetingAnalysis.request).mock.calls;
  expect(calls[1][0].request_id).not.toBe(calls[0][0].request_id);
  await settle();
});

it('recovers an accepted receipt from the URL without submitting another analysis', async () => {
  const value = receipt(); value.items[0].stages.profile!.waiting_for = 'job';
  vi.mocked(api.meetingAnalysis.progress).mockResolvedValue(value);
  renderReview({ initial: `/profiles/alex?tab=overview&analysis=${RID}` });
  await open();
  expect(await screen.findByText(/Waiting for an eligible job/)).toBeVisible();
  expect(screen.getByRole('link', { name: 'Configure analysis jobs' })).toHaveAttribute('href', '/jobs');
  expect(api.meetingAnalysis.request).not.toHaveBeenCalled();
});

it('polls an accepted receipt while closed, pauses when hidden and stops bounded monitoring without calling it failed', async () => {
  vi.useFakeTimers();
  renderReview({ initial: `/profiles/alex?analysis=${RID}` }); await settle();
  expect(api.meetingAnalysis.progress).toHaveBeenCalledTimes(1);
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(api.meetingAnalysis.progress).toHaveBeenCalledTimes(1);
  hidden.mockReturnValue(false);
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); }); await settle();
  expect(api.meetingAnalysis.progress).toHaveBeenCalledTimes(2);
  vi.setSystemTime(Date.now() + 30 * 60 * 1000);
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  fireEvent.click(screen.getByRole('button', { name: 'View analysis progress' })); await settle();
  expect(screen.getByText(/Automatic monitoring paused/)).toBeVisible();
  expect(screen.getByText(/The request can still run/)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh status' })); await settle();
  expect(api.meetingAnalysis.progress).toHaveBeenCalledTimes(3);
  expect(api.meetingAnalysis.request).not.toHaveBeenCalled();
});

it('resumes a failed receipt with its existing scope and progress rather than starting a new request', async () => {
  vi.mocked(api.meetingAnalysis.progress).mockResolvedValue(receipt('failed'));
  renderReview({ initial: `/profiles/alex?analysis=${RID}` }); await open();
  fireEvent.click(await screen.findByRole('button', { name: 'Resume unfinished analysis' }));
  await waitFor(() => expect(api.meetingAnalysis.resume).toHaveBeenCalledWith(RID));
  expect(api.meetingAnalysis.request).not.toHaveBeenCalled();
  expect(await screen.findByText('Progress saved')).toBeVisible();
});

it.each([
  ['ManualAnalysisInputChanged', 'Review speaker assignments and confirm a fresh profile analysis.'],
  ['ManualAnalysisJobUnavailable', 'Enable or configure the linked job'],
  ['ProfileRevisionConflict', 'use the current profile'],
  ['StageNoProgressTimeout', 'Saved progress is kept. Resume unfinished analysis to continue.'],
])('explains %s with an actionable message and keeps the category in technical details', async (category, message) => {
  const value = receipt('failed'); value.items[0].stages.profile!.error_type = category;
  vi.mocked(api.meetingAnalysis.progress).mockResolvedValue(value);
  renderReview({ initial: `/profiles/alex?analysis=${RID}` }); await open();
  expect(await screen.findByRole('alert')).toHaveTextContent(message);
  expect(screen.getByRole('alert')).not.toHaveTextContent(category);
  expect(screen.getByText(category)).not.toBeVisible();
});

it('does not let a delayed receipt read replace a newer URL receipt', async () => {
  let resolve!: (value: MeetingAnalysisReceipt) => void;
  vi.mocked(api.meetingAnalysis.progress).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  renderReview({ initial: `/profiles/alex?analysis=${RID}` });
  fireEvent.click(screen.getByRole('button', { name: 'Other receipt' }));
  await open(); await screen.findByText('Roadmap discussion');
  await act(async () => resolve({ ...receipt('done'), items: [{ ...receipt().items[0], title: 'Stale receipt' }] }));
  expect(screen.queryByText('Stale receipt')).not.toBeInTheDocument();
});

it('clears the previous receipt while a newly navigated receipt is loading', async () => {
  let resolve!: (value: MeetingAnalysisReceipt) => void;
  renderReview({ initial: `/profiles/alex?analysis=${RID}` }); await open(); await screen.findByText('Roadmap discussion');
  vi.mocked(api.meetingAnalysis.progress).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  fireEvent.click(screen.getByRole('button', { name: 'Other receipt' }));
  expect(screen.queryByText('Roadmap discussion')).not.toBeInTheDocument();
  expect(screen.getByText('Loading analysis progress...')).toBeVisible();
  await act(async () => resolve({ ...receipt(), request_id: 'b3b8c4d5-e678-4567-89ab-cdef01234567' }));
  expect(await screen.findByText('Roadmap discussion')).toBeVisible();
});

it.each(['resolve', 'reject'] as const)('ignores a delayed old Resume %s after navigating to another receipt', async outcome => {
  let resolve!: (value: MeetingAnalysisReceipt) => void; let reject!: (error: Error) => void;
  vi.mocked(api.meetingAnalysis.progress).mockImplementation(async id => ({ ...receipt(id === RID ? 'failed' : 'done'), request_id: id, items: [{ ...receipt().items[0], title: id === RID ? 'Roadmap discussion' : 'New receipt meeting' }] }));
  vi.mocked(api.meetingAnalysis.resume).mockReturnValueOnce(new Promise((done, fail) => { resolve = done; reject = fail; }));
  renderReview({ initial: `/profiles/alex?analysis=${RID}` }); await open();
  fireEvent.click(await screen.findByRole('button', { name: 'Resume unfinished analysis' }));
  fireEvent.click(screen.getByRole('button', { name: 'Other receipt' }));
  await screen.findByText('New receipt meeting');
  await act(async () => { if (outcome === 'resolve') resolve(receipt('continued')); else reject(new ApiError('Old source changed', 409)); });
  expect(screen.getByText('New receipt meeting')).toBeVisible();
  expect(screen.queryByText('Roadmap discussion')).not.toBeInTheDocument();
  expect(screen.queryByText(/Old source changed/)).not.toBeInTheDocument();
});

it('ignores an in-flight status read when a Resume mutation supplies a newer receipt', async () => {
  let resolve!: (value: MeetingAnalysisReceipt) => void;
  vi.mocked(api.meetingAnalysis.progress).mockResolvedValueOnce(receipt('failed')).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  renderReview({ initial: `/profiles/alex?analysis=${RID}` }); await open();
  fireEvent.click(await screen.findByRole('button', { name: 'Refresh status' }));
  fireEvent.click(screen.getByRole('button', { name: 'Resume unfinished analysis' }));
  await screen.findByText('Progress saved');
  await act(async () => resolve({ ...receipt('failed'), items: [{ ...receipt().items[0], title: 'Outdated status' }] }));
  expect(screen.queryByText('Outdated status')).not.toBeInTheDocument();
  expect(screen.getByText('Progress saved')).toBeVisible();
});

it('does not refresh or replace navigation when a submitted request finishes after unmount', async () => {
  let resolve!: (value: MeetingAnalysisReceipt) => void;
  vi.mocked(api.meetingAnalysis.request).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  const { unmount } = renderReview(); await open(); await selectAndReview();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm analysis' }));
  unmount(); await act(async () => resolve(receipt()));
  expect(changed).not.toHaveBeenCalled();
});

it('adds an accepted receipt to the current tab and filters after a pending submission', async () => {
  let resolve!: (value: MeetingAnalysisReceipt) => void;
  vi.mocked(api.meetingAnalysis.request).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  renderReview(); await open(); await selectAndReview();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm analysis' }));
  const input = vi.mocked(api.meetingAnalysis.request).mock.calls[0][0];
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getByRole('button', { name: 'Evidence tab' }));
  await act(async () => resolve({ ...receipt(), request_id: input.request_id }));
  expect(screen.getByTestId('location')).toHaveTextContent('tab=evidence');
  expect(screen.getByTestId('location')).toHaveTextContent('category=driver');
  expect(screen.getByTestId('location')).toHaveTextContent(`analysis=${input.request_id}`);
  expect(api.meetingAnalysis.request).toHaveBeenCalledTimes(1);
});

it('keeps the dialog keyboard-cancelable and restores focus to its trigger', async () => {
  renderReview(); const dialog = await open();
  fireEvent(dialog, new Event('cancel', { bubbles: true, cancelable: true }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Review past meetings' })).toHaveFocus();
});
