import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { ProfileDetailPage } from '../ProfileDetailPage';
import { profileFixture } from './profileFixture';
import type { ParticipantProfile } from '../../api';

const navigate = vi.fn();
vi.mock('react-router', async importOriginal => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useParams: () => ({ id: profileFixture.id }), useNavigate: () => navigate };
});
vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { meetings: { profile: vi.fn(), correctClaim: vi.fn(), deleteProfile: vi.fn() } } };
});
import { api, ApiError } from '../../api';

const read = vi.mocked(api.meetings.profile);
const correct = vi.mocked(api.meetings.correctClaim);
const remove = vi.mocked(api.meetings.deleteProfile);

beforeEach(() => {
  vi.clearAllMocks();
  read.mockResolvedValue(profileFixture);
  correct.mockResolvedValue(profileFixture);
  remove.mockResolvedValue({ deleted: true, id: profileFixture.id });
});
afterEach(() => vi.restoreAllMocks());

describe('ProfileDetailPage', () => {
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
    const button = await screen.findByRole('button', { name: 'Delete profile' });
    fireEvent.click(button);
    expect(remove).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(button);
    await waitFor(() => expect(remove).toHaveBeenCalledWith(profileFixture.id, 1));
    expect(navigate).toHaveBeenCalledWith('/meetings');
  });

  it('keeps failures generic and offers navigation for an unavailable profile', async () => {
    read.mockRejectedValue(new Error('PRIVATE_PROFILE_DETAIL'));
    renderWithProviders(<ProfileDetailPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('It may be unavailable or deleted.');
    expect(screen.queryByText(/PRIVATE_PROFILE_DETAIL/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to meetings' })).toHaveAttribute('href', '/meetings');
  });
});
