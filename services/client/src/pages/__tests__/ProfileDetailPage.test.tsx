import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { ProfileDetailPage } from '../ProfileDetailPage';
import { profileFixture } from './profileFixture';
import type { ParticipantProfile } from '../../api';
import { POLL_INTERVAL_MS } from '../../constants';

const navigate = vi.fn();
vi.mock('react-router', async importOriginal => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useParams: () => ({ id: profileFixture.id }), useNavigate: () => navigate };
});
vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { profiles: { get: vi.fn(), correctClaim: vi.fn(), remove: vi.fn(), update: vi.fn(), list: vi.fn(), merge: vi.fn(), linkEmail: vi.fn() } } };
});
import { api, ApiError } from '../../api';

const read = vi.mocked(api.profiles.get);
const correct = vi.mocked(api.profiles.correctClaim);
const remove = vi.mocked(api.profiles.remove);

beforeEach(() => {
  vi.clearAllMocks();
  read.mockResolvedValue(profileFixture);
  correct.mockResolvedValue(profileFixture);
  remove.mockResolvedValue({ deleted: true, id: profileFixture.id });
  vi.mocked(api.profiles.update).mockResolvedValue(profileFixture);
  vi.mocked(api.profiles.list).mockResolvedValue({ items: [], total: 0 });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('ProfileDetailPage', () => {
  it('does not claim there is no meeting evidence for a metadata-only persona update', async () => {
    read.mockResolvedValue({ ...profileFixture, claims: [], metadata: { company: 'Paralign' }, metadata_provenance: {
      company: { meeting_id: 'meeting-source', transcript_hash: 'hash', participants_revision: 0,
        evidence: [{ segment_id: 'segment-4', quote: 'I work at Paralign.' }] },
    } });
    renderWithProviders(<ProfileDetailPage />);
    await screen.findByText('I work at Paralign.');
    expect(screen.queryByText(/No meeting evidence yet/)).not.toBeInTheDocument();
  });

  it('uses the shared header for profile editing, saving and cancellation', async () => {
    let finishSave: (profile: ParticipantProfile) => void = () => undefined;
    vi.mocked(api.profiles.update).mockReturnValueOnce(new Promise(resolve => { finishSave = resolve; }));
    renderWithProviders(<ProfileDetailPage />);
    const edit = await screen.findByRole('button', { name: 'Edit' });
    const header = edit.parentElement!.parentElement!;
    expect(header).toContainElement(screen.getByRole('button', { name: /Back to profiles/ }));
    expect(header).toContainElement(screen.getByRole('button', { name: 'Delete' }));
    expect(edit).toHaveClass('btn');
    expect(edit).not.toHaveClass('btn-primary');
    fireEvent.click(edit);
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save profile' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Alex Morgan' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith(profileFixture.id, {
      expected_revision: 1, display_name: 'Alex Morgan', tags: [], starred: false,
    }));
    expect(screen.getByLabelText('Name')).toBeDisabled();
    expect(screen.getByLabelText('Company')).toBeDisabled();
    expect(screen.getByLabelText('Other')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
    await act(async () => { finishSave(profileFixture); });
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Unsaved draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
    expect(api.profiles.update).toHaveBeenCalledTimes(1);
  });

  it('retains a note draft when the conflict refresh fails, then recovers without remounting', async () => {
    let failRefresh: (failure: Error) => void = () => undefined;
    read.mockResolvedValueOnce(profileFixture).mockReturnValueOnce(new Promise((_, reject) => { failRefresh = reject; }));
    vi.mocked(api.profiles.update).mockRejectedValueOnce(new ApiError('Changed profile', 409));
    renderWithProviders(<ProfileDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit strengths notes' }));
    fireEvent.change(screen.getByLabelText('Your strengths notes'), { target: { value: 'Keep this human note.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    await act(async () => { failRefresh(new Error('Temporary failure')); });
    expect(await screen.findByText(/Could not refresh this profile/)).toBeInTheDocument();
    expect(screen.getByLabelText('Your strengths notes')).toHaveValue('Keep this human note.');
    expect(screen.getByRole('heading', { name: 'Alex' })).toBeInTheDocument();
    read.mockResolvedValue({ ...profileFixture, revision: 2 });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Revision 2')).toBeInTheDocument();
    expect(screen.getByLabelText('Your strengths notes')).toHaveValue('Keep this human note.');
    fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenLastCalledWith(profileFixture.id, { expected_revision: 2, section_notes: { strengths: 'Keep this human note.' } }));
  });

  it('groups claims, labels hypotheses and directed perceptions, and cites exact evidence', async () => {
    renderWithProviders(<ProfileDetailPage />);
    expect(await screen.findByRole('heading', { name: 'Alex' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Perceptions' })).toBeInTheDocument();
    expect(screen.getByText('Hypothesis')).toBeInTheDocument();
    expect(screen.getByText('medium confidence')).toBeInTheDocument();
    expect(screen.getByText('About Jordan')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Source evidence'));
    expect(screen.getByText(profileFixture.claims[0].evidence[0].quote)).toBeVisible();
    expect(screen.getByRole('link', { name: 'View source meeting' })).toHaveAttribute('href', `/meetings/${profileFixture.claims[0].meeting_id}#meeting-transcript`);
    expect(screen.getByRole('link', { name: 'Open original meeting' })).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('keeps meeting-only identities explicit and suppresses unsafe external links', async () => {
    read.mockResolvedValue({ ...profileFixture, email: null, identity_scope: 'meeting', claims: [{ ...profileFixture.claims[0], source_url: 'javascript:alert(1)' }] });
    renderWithProviders(<ProfileDetailPage />);
    expect(await screen.findByText(/Identified in this meeting only/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open original meeting' })).not.toBeInTheDocument();
  });

  it('explains that a manual profile can collect linked meeting evidence', async () => {
    read.mockResolvedValue({ ...profileFixture, email: null, identity_scope: 'manual', claims: [] });
    renderWithProviders(<ProfileDetailPage />);
    expect(await screen.findByText(/Manually created profile/)).toBeInTheDocument();
    expect(screen.getByText(/No meeting evidence yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add email' })).toBeInTheDocument();
    expect(screen.queryByText(/Identified in this meeting only/)).not.toBeInTheDocument();
  });

  it('requires a reason and corrected content before submitting', async () => {
    renderWithProviders(<ProfileDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Correct claim' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
    expect(screen.getByRole('alert')).toHaveTextContent('A reason is required.');
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'The speaker clarified this.' } });
    fireEvent.change(screen.getByLabelText('Corrected claim'), { target: { value: ' ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Corrected content is required.');
    expect(correct).not.toHaveBeenCalled();
  });

  it('submits a revision snapshot and displays corrected content with original evidence', async () => {
    const changed: ParticipantProfile = { ...profileFixture, revision: 2, claims: [{ ...profileFixture.claims[0], status: 'corrected', correction: {
      action: 'correct', content: 'Alex requested a date for coordination.', reason: 'The speaker clarified their intent.', corrected_at: '2026-10-28T12:01:00Z',
    } }] };
    correct.mockImplementationOnce(async () => { read.mockResolvedValue(changed); return changed; });
    renderWithProviders(<ProfileDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Correct claim' }));
    fireEvent.change(screen.getByLabelText('Corrected claim'), { target: { value: 'Alex requested a date for coordination.' } });
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'The speaker clarified their intent.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
    await waitFor(() => expect(correct).toHaveBeenCalledWith(profileFixture.id, profileFixture.claims[0].id, {
      expected_revision: 1, action: 'correct', content: 'Alex requested a date for coordination.', reason: 'The speaker clarified their intent.',
    }));
    expect(await screen.findByText('Corrected by you')).toBeInTheDocument();
    expect(screen.getByText('Alex requested a date for coordination.')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Original claim'));
    expect(screen.getByText(profileFixture.claims[0].content)).toBeVisible();
    expect(screen.getByText(profileFixture.claims[0].evidence[0].quote)).toBeInTheDocument();
  });

  it('keeps rejected claims visible with a human review label', async () => {
    const rejected: ParticipantProfile = { ...profileFixture, revision: 2, claims: [{ ...profileFixture.claims[0], status: 'rejected', correction: {
      action: 'reject', content: null, reason: 'This interpretation is incorrect.', corrected_at: '2026-10-28T12:01:00Z',
    } }] };
    correct.mockImplementationOnce(async () => { read.mockResolvedValue(rejected); return rejected; });
    renderWithProviders(<ProfileDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Reject claim' }));
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'This interpretation is incorrect.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm rejection' }));
    await waitFor(() => expect(correct).toHaveBeenCalledWith(profileFixture.id, profileFixture.claims[0].id, {
      expected_revision: 1, action: 'reject', reason: 'This interpretation is incorrect.',
    }));
    expect(await screen.findByText('Rejected by you')).toBeInTheDocument();
    expect(screen.getByText('Reason: This interpretation is incorrect.')).toBeInTheDocument();
  });

  it('refreshes a conflict while preserving the draft for an explicit resubmission', async () => {
    correct.mockRejectedValueOnce(new ApiError('PRIVATE_CONFLICT_DETAIL', 409));
    renderWithProviders(<ProfileDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Correct claim' }));
    fireEvent.change(screen.getByLabelText('Corrected claim'), { target: { value: 'Keep this correction draft.' } });
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Keep this reason.' } });
    read.mockResolvedValue({ ...profileFixture, revision: 2 });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
    expect(await screen.findByText('Revision 2')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Review the latest version and submit again.');
    expect(screen.getByLabelText('Corrected claim')).toHaveValue('Keep this correction draft.');
    expect(screen.queryByText('PRIVATE_CONFLICT_DETAIL')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
    await waitFor(() => expect(correct).toHaveBeenLastCalledWith(profileFixture.id, profileFixture.claims[0].id, {
      expected_revision: 2, action: 'correct', content: 'Keep this correction draft.', reason: 'Keep this reason.',
    }));
  });

  it('confirms profile deletion and submits the visible revision', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderWithProviders(<ProfileDetailPage />);
    const button = await screen.findByRole('button', { name: 'Delete' });
    fireEvent.click(button);
    expect(remove).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(button);
    await waitFor(() => expect(remove).toHaveBeenCalledWith(profileFixture.id, 1));
    expect(navigate).toHaveBeenCalledWith('/profiles');
  });

  it('keeps failures generic and offers navigation for an unavailable profile', async () => {
    read.mockRejectedValue(new Error('PRIVATE_PROFILE_DETAIL'));
    renderWithProviders(<ProfileDetailPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('It may be unavailable or deleted.');
    expect(screen.queryByText(/PRIVATE_PROFILE_DETAIL/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Back to profiles/ }));
    expect(navigate).toHaveBeenCalledWith('/profiles');
  });

  it('refreshes cumulative evidence without hiding the current profile', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let finishPoll: (profile: ParticipantProfile) => void = () => undefined;
    read.mockResolvedValueOnce(profileFixture).mockReturnValueOnce(new Promise(resolve => { finishPoll = resolve; }));
    renderWithProviders(<ProfileDetailPage />);
    await screen.findByText('Revision 1');

    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(screen.getByRole('heading', { name: 'Alex' })).toBeInTheDocument();
    expect(screen.queryByText('Loading participant profile...')).not.toBeInTheDocument();
    const updated: ParticipantProfile = { ...profileFixture, revision: 2, claims: [
      ...profileFixture.claims,
      { ...profileFixture.claims[0], id: 'later-claim', category: 'priority', content: 'A priority learned from a later meeting.', meeting_id: 'later-meeting' },
    ] };
    await act(async () => { finishPoll(updated); });
    expect(await screen.findByText('A priority learned from a later meeting.')).toBeInTheDocument();
    expect(screen.getByText('Revision 2')).toBeInTheDocument();
  });

  it('keeps the correction draft and captured revision when an earlier poll finishes during editing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let finishPoll: (profile: ParticipantProfile) => void = () => undefined;
    read.mockResolvedValueOnce(profileFixture).mockReturnValueOnce(new Promise(resolve => { finishPoll = resolve; }));
    correct.mockRejectedValueOnce(new ApiError('Changed profile', 409));
    renderWithProviders(<ProfileDetailPage />);
    await screen.findByText('Revision 1');
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    fireEvent.click(screen.getByRole('button', { name: 'Correct claim' }));
    fireEvent.change(screen.getByLabelText('Corrected claim'), { target: { value: 'My correction draft.' } });
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'My correction reason.' } });
    const updated = { ...profileFixture, revision: 2 };
    read.mockResolvedValue(updated);
    await act(async () => { finishPoll(updated); });
    expect(screen.getByText('Revision 2')).toBeInTheDocument();
    expect(screen.getByLabelText('Corrected claim')).toHaveValue('My correction draft.');
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(read).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
    await waitFor(() => expect(correct).toHaveBeenCalledWith(profileFixture.id, profileFixture.claims[0].id, {
      expected_revision: 1, action: 'correct', content: 'My correction draft.', reason: 'My correction reason.',
    }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Review the latest version and submit again.');
    expect(screen.getByLabelText('Corrected claim')).toHaveValue('My correction draft.');
  });

  it('redirects an old identity to its canonical profile and edits the canonical ID', async () => {
    const winner = { ...profileFixture, id: 'canonical-profile' };
    read.mockResolvedValue(winner);
    renderWithProviders(<ProfileDetailPage />);
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/profiles/canonical-profile', { replace: true }));
    fireEvent.click(screen.getByRole('button', { name: 'Star Alex' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith('canonical-profile', { expected_revision: 1, starred: true }));
  });
});
