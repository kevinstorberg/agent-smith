import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { ProfileEvidence } from '../ProfileEvidence';
import type { ParticipantProfile, ProfileClaimsPage } from '../../api';
import { POLL_INTERVAL_MS } from '../../constants';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { profiles: { claims: vi.fn(), correctClaim: vi.fn() } } }));
import { api, ApiError } from '../../api';
const reload = vi.fn();
const busy = vi.fn();
const page: ProfileClaimsPage = { profile_id: profileFixture.id, revision: 1, items: profileFixture.claims, total: 1 };
const props = { profile: profileFixture, active: true, disabled: false, onBusyChange: busy, onReload: reload };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.profiles.claims).mockResolvedValue(page); vi.mocked(api.profiles.correctClaim).mockResolvedValue(profileFixture); });
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });
async function openObservation() { fireEvent.click(await screen.findByRole('button', { name: 'View observation' })); }

it('reads a bounded page, labels hypotheses and known targets, and discloses exact source evidence', async () => {
  renderWithProviders(<ProfileEvidence {...props} />);
  expect(await screen.findByText(profileFixture.claims[0].content)).toBeVisible();
  expect(api.profiles.claims).toHaveBeenCalledWith(profileFixture.id, { limit: 20, offset: 0, sort: 'newest' });
  expect(screen.getByText('Hypothesis')).toBeVisible();
  expect(screen.getByText('medium')).toBeVisible();
  await openObservation();
  expect(screen.getByRole('link', { name: 'Jordan' })).toHaveAttribute('href', `/profiles/${profileFixture.claims[0].target_id}`);
  expect(screen.getByText(profileFixture.claims[0].evidence[0].quote)).not.toBeVisible();
  fireEvent.click(screen.getByText('Source evidence'));
  expect(screen.getByText(profileFixture.claims[0].evidence[0].quote)).toBeVisible();
  expect(screen.getByRole('link', { name: 'View source meeting' })).toHaveAttribute('href', `/meetings/${profileFixture.claims[0].meeting_id}#meeting-transcript`);
  expect(screen.getByRole('link', { name: 'Open original meeting' })).toHaveAttribute('rel', 'noopener noreferrer');
});

it('suppresses unsafe source URLs', async () => {
  vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, items: [{ ...page.items[0], source_url: 'javascript:alert(1)' }] });
  renderWithProviders(<ProfileEvidence {...props} />);
  await openObservation();
  expect(screen.queryByRole('link', { name: 'Open original meeting' })).not.toBeInTheDocument();
});

it('requires a reason and nonblank corrected content before submitting', async () => {
  renderWithProviders(<ProfileEvidence {...props} />);
  await openObservation();
  fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  expect(screen.getByRole('alert')).toHaveTextContent('A reason is required.');
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Source correction' } });
  fireEvent.change(screen.getByLabelText('Corrected claim'), { target: { value: ' ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Corrected content is required.');
  expect(api.profiles.correctClaim).not.toHaveBeenCalled();
});

it('preserves corrections and rejection reasons while keeping source evidence available', async () => {
  const corrected = { ...page.items[0], status: 'corrected' as const, correction: { action: 'correct' as const, content: 'Alex requested a date for coordination.', reason: 'The speaker clarified their intent.', corrected_at: profileFixture.updated_at } };
  vi.mocked(api.profiles.correctClaim).mockImplementationOnce(async () => { vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, items: [corrected] }); return profileFixture; });
  renderWithProviders(<ProfileEvidence {...props} />);
  await openObservation();
  fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
  fireEvent.change(screen.getByLabelText('Corrected claim'), { target: { value: corrected.correction.content } });
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: corrected.correction.reason } });
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  await waitFor(() => expect(api.profiles.correctClaim).toHaveBeenCalledWith(profileFixture.id, page.items[0].id, { expected_revision: 1, action: 'correct', content: corrected.correction.content, reason: corrected.correction.reason }));
  expect((await screen.findAllByText('Corrected by you'))[0]).toBeVisible();
  expect(within(screen.getByRole('region', { name: 'Observation details' })).getByText(corrected.correction.content)).toBeVisible();
  fireEvent.click(screen.getByText('Original claim'));
  expect(screen.getByText(page.items[0].content)).toBeVisible();
  const rejected = { ...corrected, status: 'rejected' as const, correction: { ...corrected.correction, action: 'reject' as const, content: null } };
  vi.mocked(api.profiles.correctClaim).mockImplementationOnce(async () => { vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, items: [rejected] }); return profileFixture; });
  fireEvent.click(screen.getByRole('button', { name: 'Reject claim' }));
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: rejected.correction.reason } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm rejection' }));
  expect((await screen.findAllByText('Rejected by you'))[0]).toBeVisible();
  expect(screen.getAllByText(page.items[0].content)[0]).toHaveStyle({ textDecoration: 'line-through' });
  expect(screen.getByText(`Reason: ${rejected.correction.reason}`)).toBeVisible();
});

it('retains a conflict draft and retries with the visible observation revision instead of a newer header', async () => {
  vi.mocked(api.profiles.correctClaim).mockRejectedValueOnce(new ApiError('PRIVATE_CONFLICT_DETAIL', 409));
  vi.mocked(api.profiles.claims).mockResolvedValueOnce(page).mockResolvedValue({ ...page, revision: 2, items: [{ ...page.items[0], content: 'The refreshed saved observation.' }] });
  const { rerender } = renderWithProviders(<ProfileEvidence {...props} />);
  await openObservation();
  fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
  fireEvent.change(screen.getByLabelText('Corrected claim'), { target: { value: 'Keep my draft.' } });
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Keep my reason.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Review the latest version and submit again.');
  expect(screen.queryByText('PRIVATE_CONFLICT_DETAIL')).not.toBeInTheDocument();
  rerender(<ProfileEvidence {...props} profile={{ ...profileFixture, revision: 3 }} />);
  await screen.findAllByText('The refreshed saved observation.');
  expect(screen.getByLabelText('Corrected claim')).toHaveValue('Keep my draft.');
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  await waitFor(() => expect(api.profiles.correctClaim).toHaveBeenLastCalledWith(profileFixture.id, page.items[0].id, { expected_revision: 2, action: 'correct', content: 'Keep my draft.', reason: 'Keep my reason.' }));
});

it('captures the displayed page revision when the header advances before its evidence reload', async () => {
  let finishReload!: (value: ProfileClaimsPage) => void;
  const { rerender } = renderWithProviders(<ProfileEvidence {...props} />);
  await screen.findByText(page.items[0].content);
  vi.mocked(api.profiles.claims).mockReturnValueOnce(new Promise(resolve => { finishReload = resolve; }));
  rerender(<ProfileEvidence {...props} profile={{ ...profileFixture, revision: 2 }} />);
  await waitFor(() => expect(api.profiles.claims).toHaveBeenCalledTimes(2));
  await openObservation();
  fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Based on the displayed observation.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  await waitFor(() => expect(api.profiles.correctClaim).toHaveBeenCalledWith(profileFixture.id, page.items[0].id, expect.objectContaining({ expected_revision: 1 })));
  await act(async () => finishReload({ ...page, revision: 2 }));
});

it('keeps conflict retry disabled when the refreshed observation fails to load despite a newer header', async () => {
  vi.mocked(api.profiles.correctClaim).mockRejectedValueOnce(new ApiError('Conflict', 409));
  const { rerender } = renderWithProviders(<ProfileEvidence {...props} />);
  await openObservation();
  fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
  fireEvent.change(screen.getByLabelText('Corrected claim'), { target: { value: 'My retained draft.' } });
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'My retained reason.' } });
  vi.mocked(api.profiles.claims).mockRejectedValue(new Error('Refresh unavailable'));
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  await screen.findByText('Could not refresh this evidence. Your current view and drafts are retained.');
  rerender(<ProfileEvidence {...props} profile={{ ...profileFixture, revision: 5 }} />);
  expect(screen.getByLabelText('Corrected claim')).toHaveValue('My retained draft.');
  expect(screen.getByRole('button', { name: 'Save correction' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  expect(api.profiles.correctClaim).toHaveBeenCalledTimes(1);
  vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, revision: 3, items: [{ ...page.items[0], content: 'The current observation after recovery.' }] });
  fireEvent.click(screen.getByRole('button', { name: 'Retry evidence' }));
  await screen.findAllByText('The current observation after recovery.');
  expect(screen.getByRole('button', { name: 'Save correction' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  await waitFor(() => expect(api.profiles.correctClaim).toHaveBeenLastCalledWith(profileFixture.id, page.items[0].id, expect.objectContaining({ expected_revision: 3 })));
});

it('offers safe recovery and cancellation when a conflict refresh withdraws the edited observation', async () => {
  vi.mocked(api.profiles.correctClaim).mockRejectedValueOnce(new ApiError('Conflict', 409));
  renderWithProviders(<ProfileEvidence {...props} />);
  await openObservation();
  fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
  fireEvent.change(screen.getByLabelText('Corrected claim'), { target: { value: 'Private withdrawn draft.' } });
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'My reason.' } });
  vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, revision: 2, items: [], total: 0 });
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  expect(await screen.findByRole('region', { name: 'Evidence draft recovery' })).toBeVisible();
  expect(screen.queryByText(page.items[0].content)).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue('Private withdrawn draft.')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save correction' })).toBeDisabled();
  expect(busy).toHaveBeenLastCalledWith(true);
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.queryByRole('region', { name: 'Evidence draft recovery' })).not.toBeInTheDocument();
  expect(busy).toHaveBeenLastCalledWith(false);
});

it('restores a missing draft only after the same observation becomes visible in a successful reload', async () => {
  vi.mocked(api.profiles.correctClaim).mockRejectedValueOnce(new ApiError('Conflict', 409));
  renderWithProviders(<ProfileEvidence {...props} />);
  await openObservation();
  fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
  fireEvent.change(screen.getByLabelText('Corrected claim'), { target: { value: 'My draft to recover.' } });
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'My reason.' } });
  vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, revision: 2, items: [{ ...page.items[0], id: 'different-claim', content: 'A different observation.' }] });
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  await screen.findByRole('region', { name: 'Evidence draft recovery' });
  expect(screen.getByRole('button', { name: 'Save correction' })).toBeDisabled();
  vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, revision: 4, items: [{ ...page.items[0], content: 'The same observation is available again.' }] });
  fireEvent.click(screen.getByRole('button', { name: 'Reload evidence' }));
  await screen.findAllByText('The same observation is available again.');
  expect(screen.getByLabelText('Corrected claim')).toHaveValue('My draft to recover.');
  expect(screen.getByRole('button', { name: 'Save correction' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  await waitFor(() => expect(api.profiles.correctClaim).toHaveBeenLastCalledWith(profileFixture.id, page.items[0].id, expect.objectContaining({ expected_revision: 4, content: 'My draft to recover.' })));
});

it('locks pagination and the submitted draft until saving finishes', async () => {
  vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, total: 40 });
  let complete!: (value: ParticipantProfile) => void;
  vi.mocked(api.profiles.correctClaim).mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
  renderWithProviders(<ProfileEvidence {...props} />);
  await openObservation();
  fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
  expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Verified source' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  expect(screen.getByLabelText('Corrected claim')).toBeDisabled();
  expect(screen.getByLabelText('Reason')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  await act(async () => complete(profileFixture));
  expect(screen.queryByLabelText('Reason')).not.toBeInTheDocument();
});

it('keeps the captured revision when an earlier poll finishes during editing', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let complete!: (value: ProfileClaimsPage) => void;
  vi.mocked(api.profiles.claims).mockResolvedValueOnce(page).mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
  const { rerender } = renderWithProviders(<ProfileEvidence {...props} />);
  await openObservation();
  await act(async () => vi.advanceTimersByTime(POLL_INTERVAL_MS));
  fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'My reason' } });
  await act(async () => complete({ ...page, revision: 2 }));
  vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, revision: 2 });
  rerender(<ProfileEvidence {...props} profile={{ ...profileFixture, revision: 2 }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
  await waitFor(() => expect(api.profiles.correctClaim).toHaveBeenCalledWith(profileFixture.id, page.items[0].id, expect.objectContaining({ expected_revision: 1 })));
});

it('keeps failures generic and retries instead of reporting an empty profile', async () => {
  vi.mocked(api.profiles.claims).mockRejectedValueOnce(new Error('PRIVATE_BACKEND_DETAIL'));
  renderWithProviders(<ProfileEvidence {...props} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not refresh this evidence.');
  expect(screen.queryByText('PRIVATE_BACKEND_DETAIL')).not.toBeInTheDocument();
  expect(screen.queryByText(/No saved observations yet/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry evidence' }));
  expect(await screen.findByText(page.items[0].content)).toBeVisible();
});

it('describes an empty observation feed without denying metadata meeting sources', async () => {
  vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, items: [], total: 0 });
  renderWithProviders(<ProfileEvidence {...props} profile={{ ...profileFixture, claims: [], metadata_provenance: {
    company: { meeting_id: 'metadata-source', evidence: [], evidence_count: 1 },
  } }} />);
  expect(await screen.findByText(/No saved observations yet/)).toBeVisible();
  expect(screen.queryByText(/No meeting evidence/)).not.toBeInTheDocument();
});

it('uses kind tabs and server filters, debounces search and resets paging before querying', async () => {
  vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, total: 45 });
  renderWithProviders(<ProfileEvidence {...props} />);
  await screen.findByText(page.items[0].content);
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await waitFor(() => expect(api.profiles.claims).toHaveBeenLastCalledWith(profileFixture.id, { limit: 20, offset: 20, sort: 'newest' }));
  fireEvent.click(screen.getByRole('button', { name: 'Hypotheses' }));
  await waitFor(() => expect(api.profiles.claims).toHaveBeenLastCalledWith(profileFixture.id, { limit: 20, offset: 0, sort: 'newest', epistemic: 'inference' }));
  fireEvent.change(screen.getByLabelText('Category'), { target: { value: 'perception' } });
  fireEvent.change(screen.getByLabelText('Confidence'), { target: { value: 'high' } });
  fireEvent.change(screen.getByLabelText('Review status'), { target: { value: 'corrected' } });
  fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'oldest' } });
  screen.getByLabelText('Search observations').focus();
  fireEvent.change(screen.getByLabelText('Search observations'), { target: { value: 'clear commitments' } });
  await waitFor(() => expect(api.profiles.claims).toHaveBeenLastCalledWith(profileFixture.id, { limit: 20, offset: 0, sort: 'oldest', epistemic: 'inference', category: 'perception', confidence: 'high', status: 'corrected', q: 'clear commitments' }));
  expect(screen.getByLabelText('Search observations')).toHaveFocus();
});

it('keeps a related-person deep link explicit and clearable', async () => {
  const target = profileFixture.claims[0].target_id!;
  renderWithProviders(<ProfileEvidence {...props} />, { initialEntries: [`/?tab=evidence&target_id=${target}`] });
  await waitFor(() => expect(api.profiles.claims).toHaveBeenLastCalledWith(profileFixture.id, { limit: 20, offset: 0, sort: 'newest', target_id: target }));
  expect(screen.getByRole('link', { name: 'related person' })).toHaveAttribute('href', `/profiles/${target}`);
  fireEvent.click(screen.getByRole('button', { name: 'Clear related person filter' }));
  await waitFor(() => expect(api.profiles.claims).toHaveBeenLastCalledWith(profileFixture.id, { limit: 20, offset: 0, sort: 'newest' }));
});

it('shows compact rows and expands only one observation at a time', async () => {
  const second = { ...page.items[0], id: 'another-claim', content: 'A second saved observation.' };
  vi.mocked(api.profiles.claims).mockResolvedValue({ ...page, items: [page.items[0], second], total: 2 });
  renderWithProviders(<ProfileEvidence {...props} />);
  await screen.findByText(second.content);
  expect(screen.queryByRole('region', { name: 'Observation details' })).not.toBeInTheDocument();
  expect(screen.queryByText(page.items[0].rationale)).not.toBeInTheDocument();
  fireEvent.click(screen.getAllByRole('button', { name: 'View observation' })[0]);
  expect(screen.getAllByRole('region', { name: 'Observation details' })).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'View observation' }));
  expect(screen.getAllByRole('region', { name: 'Observation details' })).toHaveLength(1);
  expect(within(screen.getByRole('region', { name: 'Observation details' })).getByText(second.content)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
  expect(screen.getByLabelText('Search observations')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Hypotheses' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Close details' })).toBeDisabled();
});

it('merges rapid filter changes before their URL navigations commit', async () => {
  renderWithProviders(<ProfileEvidence {...props} />);
  await screen.findByText(page.items[0].content);
  act(() => {
    fireEvent.click(screen.getByRole('button', { name: 'Hypotheses' }));
    fireEvent.change(screen.getByLabelText('Category'), { target: { value: 'perception' } });
    fireEvent.change(screen.getByLabelText('Confidence'), { target: { value: 'high' } });
    fireEvent.change(screen.getByLabelText('Review status'), { target: { value: 'corrected' } });
  });
  await waitFor(() => expect(api.profiles.claims).toHaveBeenLastCalledWith(profileFixture.id, { limit: 20, offset: 0, sort: 'newest', epistemic: 'inference', category: 'perception', confidence: 'high', status: 'corrected' }));
});
