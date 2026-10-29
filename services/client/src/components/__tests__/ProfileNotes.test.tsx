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

it('shows human notes separately and patches just the edited section, including clearing it', async () => {
  renderWithProviders(<ProfileNotes profile={{ ...profileFixture, section_notes: { drivers: 'Autonomy', strengths: 'Teaching' } }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByRole('heading', { name: 'Your notes' })).toBeInTheDocument();
  const drivers = within(screen.getByRole('region', { name: 'Drivers notes' }));
  fireEvent.click(drivers.getByRole('button', { name: 'Edit drivers notes' }));
  fireEvent.change(drivers.getByLabelText('Your drivers notes'), { target: { value: '' } });
  fireEvent.submit(drivers.getByRole('button', { name: 'Save note' }).closest('form')!);
  await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith(profileFixture.id, { expected_revision: 1, section_notes: { drivers: '' } }));
  expect(screen.getByText('Teaching')).toBeInTheDocument();
});

it('keeps the edited note on409 while preserving other refreshed sections', async () => {
  vi.mocked(api.profiles.update).mockRejectedValueOnce(new ApiError('Conflict', 409));
  const { rerender } = renderWithProviders(<ProfileNotes profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit strengths notes' }));
  fireEvent.change(screen.getByLabelText('Your strengths notes'), { target: { value: 'My draft' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Save note' }).closest('form')!);
  await screen.findByRole('alert');
  rerender(<ProfileNotes profile={{ ...profileFixture, revision: 3, section_notes: { drivers: 'Changed elsewhere' } }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByLabelText('Your strengths notes')).toHaveValue('My draft');
  fireEvent.submit(screen.getByRole('button', { name: 'Save note' }).closest('form')!);
  await waitFor(() => expect(api.profiles.update).toHaveBeenLastCalledWith(profileFixture.id, { expected_revision: 3, section_notes: { strengths: 'My draft' } }));
});

it('locks the submitted note while saving so later typing cannot be discarded', async () => {
  let finishSave: (profile: typeof profileFixture) => void = () => undefined;
  vi.mocked(api.profiles.update).mockReturnValueOnce(new Promise(resolve => { finishSave = resolve; }));
  renderWithProviders(<ProfileNotes profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit strengths notes' }));
  fireEvent.change(screen.getByLabelText('Your strengths notes'), { target: { value: 'My submitted note' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  expect(screen.getByLabelText('Your strengths notes')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  await act(async () => { finishSave(profileFixture); });
  expect(screen.queryByLabelText('Your strengths notes')).not.toBeInTheDocument();
});
