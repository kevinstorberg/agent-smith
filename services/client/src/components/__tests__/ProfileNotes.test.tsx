import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { ProfileNotes } from '../ProfileNotes';
vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { profiles: { update: vi.fn() } } }));
import { api, ApiError } from '../../api';
const reload = vi.fn();
const busy = vi.fn();
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.profiles.update).mockResolvedValue(profileFixture); });

it('shows six narrative assessments and patches just the edited section, including a protected clear', async () => {
  renderWithProviders(<ProfileNotes profile={{ ...profileFixture, section_notes: { drivers: 'Autonomy', strengths: 'Teaching' } }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getAllByRole('heading')).toHaveLength(6);
  const drivers = within(screen.getByRole('region', { name: 'Drivers and motivations assessment' }));
  fireEvent.click(drivers.getByRole('button', { name: 'Edit drivers and motivations' }));
  fireEvent.change(drivers.getByLabelText('Drivers and motivations'), { target: { value: '' } });
  fireEvent.submit(drivers.getByRole('button', { name: 'Save section' }).closest('form')!);
  await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith(profileFixture.id, { expected_revision: 1, section_notes: { drivers: '' } }));
  expect(screen.getByText('Teaching')).toBeInTheDocument();
});

it('keeps the edited note on409 while preserving other refreshed sections', async () => {
  vi.mocked(api.profiles.update).mockRejectedValueOnce(new ApiError('Conflict', 409));
  const { rerender } = renderWithProviders(<ProfileNotes profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit strengths' }));
  fireEvent.change(screen.getByLabelText('Strengths'), { target: { value: 'My draft' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Save section' }).closest('form')!);
  await screen.findByRole('alert');
  rerender(<ProfileNotes profile={{ ...profileFixture, revision: 3, section_notes: { drivers: 'Changed elsewhere' } }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByLabelText('Strengths')).toHaveValue('My draft');
  fireEvent.submit(screen.getByRole('button', { name: 'Save section' }).closest('form')!);
  await waitFor(() => expect(api.profiles.update).toHaveBeenLastCalledWith(profileFixture.id, { expected_revision: 3, section_notes: { strengths: 'My draft' } }));
});

it('locks the submitted note while saving so later typing cannot be discarded', async () => {
  let finishSave: (profile: typeof profileFixture) => void = () => undefined;
  vi.mocked(api.profiles.update).mockReturnValueOnce(new Promise(resolve => { finishSave = resolve; }));
  renderWithProviders(<ProfileNotes profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit strengths' }));
  fireEvent.change(screen.getByLabelText('Strengths'), { target: { value: 'My submitted note' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save section' }));
  expect(screen.getByLabelText('Strengths')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  await act(async () => { finishSave(profileFixture); });
  expect(screen.queryByLabelText('Strengths')).not.toBeInTheDocument();
});

it('preserves a human-cleared section until automatic updates are explicitly allowed', async () => {
  renderWithProviders(<ProfileNotes profile={{ ...profileFixture, section_notes: { overview: '' }, section_evidence: { overview: { human: true } } }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByText('You have kept this section empty.')).toBeInTheDocument();
  expect(api.profiles.update).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Allow automatic updates to overview' }));
  await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith(profileFixture.id, { expected_revision: 1, allow_agent_sections: ['overview'] }));
});

it('puts the narrative first and keeps only accepted observations under a collapsed disclosure', () => {
  renderWithProviders(<ProfileNotes profile={{ ...profileFixture, section_notes: { drivers: 'Alex values clear ownership and reliable commitments.' }, section_evidence: { drivers: { human: false, status: 'supported', claim_ids: [profileFixture.claims[0].id], coverage: { claim_count: 1, meeting_count: 1 } } } }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByText('Alex values clear ownership and reliable commitments.')).toBeVisible();
  expect(screen.getByText('Updated automatically · 1 observation from 1 meeting')).toBeInTheDocument();
  const evidence = screen.getByText('Supporting evidence (1)').closest('details');
  expect(evidence).not.toHaveAttribute('open');
  expect(screen.getByText(profileFixture.claims[0].content)).not.toBeVisible();
  fireEvent.click(screen.getByText('Supporting evidence (1)'));
  expect(screen.getByText(profileFixture.claims[0].content)).toBeVisible();
});
