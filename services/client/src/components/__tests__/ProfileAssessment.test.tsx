import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { ProfileAssessment } from '../ProfileAssessment';
import type { ProfileBuildResult } from '../../api';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { profiles: { rebuild: vi.fn() } } }));
import { api, ApiError } from '../../api';
const reload = vi.fn();
const busy = vi.fn();
const result: ProfileBuildResult = { job_id: 42, profile_id: profileFixture.id, execution_id: 87, success: true, output: JSON.stringify({ assessments: { outcome: 'done', profiles: 1 } }), error: '', duration_seconds: 2, exit_code: null };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.profiles.rebuild).mockResolvedValue(result); });

it('runs only after an explicit click, uses the captured revision, and links the exact execution', async () => {
  let complete!: (result: ProfileBuildResult) => void;
  vi.mocked(api.profiles.rebuild).mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
  renderWithProviders(<ProfileAssessment profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(api.profiles.rebuild).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Build assessment' }));
  expect(api.profiles.rebuild).toHaveBeenCalledWith(profileFixture.id, 1);
  expect(screen.getByRole('button', { name: 'Updating assessment...' })).toBeDisabled();
  await act(async () => complete(result));
  expect(screen.getByRole('status')).toHaveTextContent('Updated 1 profile assessment.');
  expect(screen.getByRole('link', { name: 'View assessment execution #87' })).toHaveAttribute('href', '/jobs/42?tab=executions&execution=87');
  expect(reload).toHaveBeenCalledTimes(1);
});

it('explains missing job configuration and preserves an explicit retry', async () => {
  vi.mocked(api.profiles.rebuild).mockRejectedValueOnce(new ApiError('Create a persona graph job first.', 409));
  renderWithProviders(<ProfileAssessment profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Build assessment' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Create a persona graph job first.');
  expect(screen.getByRole('link', { name: 'Create persona job' })).toHaveAttribute('href', '/jobs/new?graph=persona');
  expect(screen.getByRole('button', { name: 'Build assessment' })).toBeEnabled();
});

it('does not refresh an abandoned profile after a long-running assessment finishes', async () => {
  let complete!: (result: ProfileBuildResult) => void;
  vi.mocked(api.profiles.rebuild).mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
  const { unmount } = renderWithProviders(<ProfileAssessment profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Build assessment' }));
  unmount();
  await act(async () => complete(result));
  expect(reload).not.toHaveBeenCalled();
});

it('does not offer a build without evidence and explains protected empty profiles', () => {
  renderWithProviders(<ProfileAssessment profile={{ ...profileFixture, claims: [], assessment: { status: 'insufficient_evidence', attempts: 0, next_attempt_at: null, error: null, coverage: { claim_count: 0, meeting_count: 0 }, can_generate: false } }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByRole('button', { name: 'Build assessment' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Review past meetings' })).toBeEnabled();
  expect(screen.getByText(/More evidence is needed/)).toBeInTheDocument();
});

it.each([
  ['continued', 'Assessment progress saved.', 'status'],
  ['idle', 'No assessment changes were needed.', 'status'],
  ['failed', 'Assessment update failed.', 'alert'],
])('reports an assessment %s result without claiming successful completion', async (outcome, message, role) => {
  vi.mocked(api.profiles.rebuild).mockResolvedValue({ ...result, output: JSON.stringify({ profiles: { outcome: 'idle' }, assessments: { outcome, profiles: 0 } }) });
  renderWithProviders(<ProfileAssessment profile={{ ...profileFixture, section_notes: { overview: 'Existing assessment' } }} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Refresh assessment' }));
  await waitFor(() => expect(screen.getByRole(role)).toHaveTextContent(message));
});
