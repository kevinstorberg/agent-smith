import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import type { ProfileRelationship } from '../../api';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { ProfileRelationships } from '../ProfileRelationships';
vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { profiles: { list: vi.fn(), createRelationship: vi.fn(), updateRelationship: vi.fn(), removeRelationship: vi.fn() } } }));
import { api, ApiError } from '../../api';
const reload = vi.fn(); const busy = vi.fn();
const other = { ...profileFixture, id: 'other-profile', display_name: 'Jordan', email: 'jordan@example.test', created_at: profileFixture.updated_at, meeting_count: 1, claim_count: 1 };
const edge: ProfileRelationship = { id: 'edge-id', subject_id: other.id, target_id: profileFixture.id, subject_name: 'Jordan', target_name: 'Alex', label: 'reports to', notes: 'Human context', revision: 2, dismissed: false, claims: [], created_at: profileFixture.updated_at, updated_at: profileFixture.updated_at };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.profiles.list).mockResolvedValue({ items: [other], total: 1 }); vi.mocked(api.profiles.createRelationship).mockResolvedValue(edge); vi.mocked(api.profiles.updateRelationship).mockResolvedValue(edge); vi.mocked(api.profiles.removeRelationship).mockResolvedValue({ deleted: true, id: edge.id }); });

it('creates an explicitly directed relationship using both captured profile revisions', async () => {
  renderWithProviders(<ProfileRelationships profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Add relationship' }));
  expect(screen.getByText('Relationship from Alex to the selected person.')).toBeInTheDocument();
  await screen.findByRole('option', { name: 'Jordan · jordan@example.test' });
  fireEvent.change(screen.getByLabelText('Related profile'), { target: { value: other.id } });
  fireEvent.change(screen.getByLabelText('Relationship label'), { target: { value: ' works with ' } });
  fireEvent.change(screen.getByLabelText('Your relationship notes'), { target: { value: ' Human note ' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Save relationship' }).closest('form')!);
  await waitFor(() => expect(api.profiles.createRelationship).toHaveBeenCalledWith(profileFixture.id, { target_id: other.id, target_revision: 1, expected_revision: 1, label: 'works with', notes: 'Human note' }));
  expect(reload).toHaveBeenCalled();
});

it('preserves incoming direction and an edit draft across409 using the refreshed edge revision', async () => {
  vi.mocked(api.profiles.updateRelationship).mockRejectedValueOnce(new ApiError('Conflict', 409));
  const { rerender } = renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, relationships: [edge] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  expect(screen.getByText('Editing Jordan → Alex')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Your relationship notes'), { target: { value: 'My draft' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Save relationship' }).closest('form')!);
  await screen.findByRole('alert');
  rerender(<ProfileRelationships profile={{ ...profileFixture, relationships: [{ ...edge, revision: 4 }] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByLabelText('Your relationship notes')).toHaveValue('My draft');
  fireEvent.submit(screen.getByRole('button', { name: 'Save relationship' }).closest('form')!);
  await waitFor(() => expect(api.profiles.updateRelationship).toHaveBeenLastCalledWith(profileFixture.id, edge.id, { expected_revision: 4, label: 'reports to', notes: 'My draft' }));
});

it('removes only after explicit confirmation using the edge revision', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
  renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, relationships: [edge] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Remove relationship' }));
  expect(api.profiles.removeRelationship).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Remove relationship' }));
  await waitFor(() => expect(api.profiles.removeRelationship).toHaveBeenCalledWith(profileFixture.id, edge.id, 2));
  confirm.mockRestore();
});

it('links to paged evidence instead of rendering relationship observations in the assessment', () => {
  const claim = { ...profileFixture.claims[0], status: 'rejected' as const, correction: { action: 'reject' as const, content: null, reason: 'The speaker clarified their intent.', corrected_at: profileFixture.updated_at } };
  renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, relationships: [{ ...edge, claims: [claim] }] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByRole('link', { name: 'Meeting evidence (1)' })).toHaveAttribute('href', `/profiles/${other.id}?tab=evidence`);
  expect(screen.queryByText(claim.content)).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Jordan' })).toHaveAttribute('href', `/profiles/${other.id}`);
});

it('locks the captured relationship draft until the save finishes', async () => {
  let finishSave: (relationship: ProfileRelationship) => void = () => undefined;
  vi.mocked(api.profiles.updateRelationship).mockReturnValueOnce(new Promise(resolve => { finishSave = resolve; }));
  renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, relationships: [edge] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  expect(screen.getByLabelText('Relationship label')).toBeDisabled();
  expect(screen.getByLabelText('Your relationship notes')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  await act(async () => { finishSave(edge); });
  expect(screen.queryByLabelText('Your relationship notes')).not.toBeInTheDocument();
});
