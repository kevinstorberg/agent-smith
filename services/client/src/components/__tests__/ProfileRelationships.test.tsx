import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import type { ProfileRelationship } from '../../api';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { ProfileRelationships } from '../ProfileRelationships';
vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { profiles: { update: vi.fn(), list: vi.fn(), createRelationship: vi.fn(), updateRelationship: vi.fn(), removeRelationship: vi.fn() } } }));
import { api, ApiError } from '../../api';
const reload = vi.fn(); const busy = vi.fn();
const other = { ...profileFixture, id: 'other-profile', display_name: 'Jordan', email: 'jordan@example.test', created_at: profileFixture.updated_at, meeting_count: 1, claim_count: 1 };
const edge: ProfileRelationship = { id: 'edge-id', subject_id: other.id, target_id: profileFixture.id, subject_name: 'Jordan', target_name: 'Alex', label: 'reports to', notes: 'Human context', revision: 2, dismissed: false, claims: [], created_at: profileFixture.updated_at, updated_at: profileFixture.updated_at };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.profiles.update).mockResolvedValue(profileFixture); vi.mocked(api.profiles.list).mockResolvedValue({ items: [other], total: 1 }); vi.mocked(api.profiles.createRelationship).mockResolvedValue(edge); vi.mocked(api.profiles.updateRelationship).mockResolvedValue(edge); vi.mocked(api.profiles.removeRelationship).mockResolvedValue({ deleted: true, id: edge.id }); });

it('creates an explicitly directed relationship using both captured profile revisions', async () => {
  renderWithProviders(<ProfileRelationships profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Add relationship' }));
  expect(screen.getByText('Relationship from Alex to the selected person.')).toBeInTheDocument();
  await screen.findByRole('option', { name: 'Jordan · jordan@example.test' });
  fireEvent.change(screen.getByLabelText('Related profile'), { target: { value: other.id } });
  fireEvent.change(screen.getByLabelText('Relationship label'), { target: { value: ' works with ' } });
  fireEvent.change(screen.getByLabelText('Relationship assessment'), { target: { value: ' Human note ' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Save relationship' }).closest('form')!);
  await waitFor(() => expect(api.profiles.createRelationship).toHaveBeenCalledWith(profileFixture.id, { target_id: other.id, target_revision: 1, expected_revision: 1, label: 'works with', notes: 'Human note' }));
  expect(reload).toHaveBeenCalled();
});

it('preserves incoming direction and an edit draft across409 using the refreshed edge revision', async () => {
  vi.mocked(api.profiles.updateRelationship).mockRejectedValueOnce(new ApiError('Conflict', 409));
  const { rerender } = renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, relationships: [edge] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  expect(screen.getByText('Editing Jordan → Alex')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Relationship assessment'), { target: { value: 'My draft' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Save relationship' }).closest('form')!);
  await screen.findByRole('alert');
  rerender(<ProfileRelationships profile={{ ...profileFixture, relationships: [{ ...edge, revision: 4 }] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByLabelText('Relationship assessment')).toHaveValue('My draft');
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
  expect(screen.getByRole('link', { name: 'Meeting evidence (1)' })).toHaveAttribute('href', `/profiles/${other.id}?tab=evidence&target_id=${profileFixture.id}`);
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
  expect(screen.getByLabelText('Relationship assessment')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  await act(async () => { finishSave(edge); });
  expect(screen.queryByLabelText('Relationship assessment')).not.toBeInTheDocument();
});

it('groups reciprocal perspectives in one linked person entry without duplicating their analyses', () => {
  const outgoing = { ...edge, id: 'reverse-edge', subject_id: profileFixture.id, target_id: other.id, subject_name: 'Alex', target_name: 'Jordan', notes: 'Alex values Jordan’s judgment.', analysis_evidence: { human: false, status: 'supported' as const, claim_count: 2 } };
  renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, relationships: [edge, outgoing], section_notes: { relationships: 'Old combined relationship narrative.' } }} disabled={false} onBusyChange={busy} onReload={reload} />);
  const person = within(screen.getByRole('article', { name: 'Relationship with Jordan' }));
  expect(screen.getAllByRole('article')).toHaveLength(1);
  expect(person.getByText('Jordan → Alex')).toBeVisible();
  expect(person.getByText('Alex → Jordan')).toBeVisible();
  expect(person.getByText('Human context')).toBeVisible();
  expect(person.getByText(outgoing.notes)).toBeVisible();
  expect(person.getAllByRole('button', { name: 'Edit relationship' })).toHaveLength(2);
  expect(screen.queryByText('Old combined relationship narrative.')).not.toBeInTheDocument();
});

it('keeps a label-only change from protecting an unchanged generated assessment', async () => {
  renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, relationships: [edge] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  fireEvent.change(screen.getByLabelText('Relationship label'), { target: { value: 'Collaborator' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await waitFor(() => expect(api.profiles.updateRelationship).toHaveBeenCalledWith(profileFixture.id, edge.id, { expected_revision: 2, label: 'Collaborator' }));
});

it('protects a deliberately cleared assessment and releases it only explicitly', async () => {
  const { rerender } = renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, relationships: [edge] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  fireEvent.change(screen.getByLabelText('Relationship assessment'), { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await waitFor(() => expect(api.profiles.updateRelationship).toHaveBeenCalledWith(profileFixture.id, edge.id, { expected_revision: 2, label: 'reports to', notes: '' }));
  rerender(<ProfileRelationships profile={{ ...profileFixture, relationships: [{ ...edge, revision: 3, notes: '', analysis_evidence: { human: true } }] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByText('You have kept this assessment empty.')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Allow automatic updates' }));
  await waitFor(() => expect(api.profiles.updateRelationship).toHaveBeenLastCalledWith(profileFixture.id, edge.id, { expected_revision: 3, allow_agent_notes: true }));
});

it('omits an untouched assessment on a new link so future analysis can fill it', async () => {
  renderWithProviders(<ProfileRelationships profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Add relationship' }));
  await screen.findByRole('option', { name: 'Jordan · jordan@example.test' });
  fireEvent.change(screen.getByLabelText('Related profile'), { target: { value: other.id } });
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await waitFor(() => expect(api.profiles.createRelationship).toHaveBeenCalledWith(profileFixture.id, { target_id: other.id, target_revision: 1, expected_revision: 1, label: '' }));
});

it('keeps Cancel accessible when a conflicted relationship disappears', async () => {
  vi.mocked(api.profiles.updateRelationship).mockRejectedValueOnce(new ApiError('Conflict', 409));
  const { rerender } = renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, relationships: [edge] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  fireEvent.change(screen.getByLabelText('Relationship assessment'), { target: { value: 'My retained draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('button', { name: 'Save relationship' })).toBeDisabled();
  rerender(<ProfileRelationships profile={{ ...profileFixture, relationships: [] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByRole('region', { name: 'Relationship draft recovery' })).toBeVisible();
  expect(screen.queryByDisplayValue('My retained draft')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(busy).toHaveBeenLastCalledWith(false);
});

it('permits an unchanged-edge retry after a successful reread of a busy409', async () => {
  vi.mocked(api.profiles.updateRelationship).mockRejectedValueOnce(new ApiError('Profiles are busy; try again', 409));
  const { rerender } = renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, relationships: [edge] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  fireEvent.change(screen.getByLabelText('Relationship assessment'), { target: { value: 'My draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('button', { name: 'Save relationship' })).toBeDisabled();
  rerender(<ProfileRelationships profile={{ ...profileFixture, relationships: [edge] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByRole('button', { name: 'Save relationship' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await waitFor(() => expect(api.profiles.updateRelationship).toHaveBeenLastCalledWith(profileFixture.id, edge.id, { expected_revision: 2, label: 'reports to', notes: 'My draft' }));
});

it.each([
  [{ relationships: 'My previous combined assessment.' }, { relationships: { human: true } }],
  [{ relationships: '' }, { relationships: { human: true } }],
  [{}, { relationships: { human: true } }],
  [{ relationships: 'Legacy human text without proof.' }, undefined],
])('preserves previous human relationship protection until explicitly released', async (section_notes, section_evidence) => {
  renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, section_notes, section_evidence }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByText(/Your previous combined relationship notes remain protected in History/)).toBeVisible();
  expect(api.profiles.update).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Allow automatic relationship updates' }));
  await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith(profileFixture.id, { expected_revision: 1, allow_agent_sections: ['relationships'] }));
});

it('does not require releasing an automatically generated legacy aggregate', () => {
  renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, section_notes: { relationships: 'Earlier automatic text.' }, section_evidence: { relationships: { human: false } } }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.queryByRole('button', { name: 'Allow automatic relationship updates' })).not.toBeInTheDocument();
});

it('uses an existing legacy proof without human ownership instead of treating its text as human', () => {
  renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, section_notes: { relationships: 'Earlier analysis.' }, section_evidence: JSON.parse('{"relationships":{"status":"supported"}}') }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.queryByRole('button', { name: 'Allow automatic relationship updates' })).not.toBeInTheDocument();
});

it('keeps released human text visible and labels permission without claiming an automatic rewrite', () => {
  renderWithProviders(<ProfileRelationships profile={{ ...profileFixture, relationships: [{ ...edge, analysis_evidence: { human: false, origin: 'human' } }] }} disabled={false} onBusyChange={busy} onReload={reload} />);
  expect(screen.getByText(edge.notes)).toBeVisible();
  expect(screen.getByText('Automatic updates allowed')).toBeVisible();
  expect(screen.queryByText('Updated automatically')).not.toBeInTheDocument();
});
