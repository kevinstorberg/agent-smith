import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterAll, beforeAll, beforeEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import type { ParticipantProfile, ProfileRelationshipCard } from '../../api';
import { profileFixture, relationshipCardFixture as card } from '../../pages/__tests__/profileFixture';
import { ProfileRelationships } from '../ProfileRelationships';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { profiles: {
  create: vi.fn(), list: vi.fn(), createRelationshipCard: vi.fn(), updateRelationshipCard: vi.fn(), removeRelationshipCard: vi.fn(),
} } }));
import { api, ApiError } from '../../api';
const reload = vi.fn(); const busy = vi.fn();
const other = { ...profileFixture, id: card.profile_id!, display_name: 'Jordan', email: 'jordan@example.test', created_at: profileFixture.updated_at, meeting_count: 1, claim_count: 1, revision: 4 };
const view = (profile: ParticipantProfile) => <ProfileRelationships profile={profile} disabled={false} onBusyChange={busy} onReload={reload} />;
const profileWith = (cards: ProfileRelationshipCard[] = [card]): ParticipantProfile => ({ ...profileFixture, relationship_cards: cards });
const originalShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal');
beforeAll(() => Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true; } }));
afterAll(() => { if (originalShowModal) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', originalShowModal); else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal'); });
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.profiles.list).mockResolvedValue({ items: [other], total: 1 });
  vi.mocked(api.profiles.createRelationshipCard).mockResolvedValue(profileWith());
  vi.mocked(api.profiles.updateRelationshipCard).mockResolvedValue(profileWith());
  vi.mocked(api.profiles.removeRelationshipCard).mockResolvedValue(profileWith([]));
});

it('renders one name, one analysis and one control set per DTO person, ignoring contradictory raw sources', () => {
  const plain = { ...card, id: 'name:casey', name: 'Casey', profile_id: null, notes: 'Alex seeks Casey’s independent technical judgment.', evidence_links: [] };
  renderWithProviders(view({ ...profileWith([card, plain]), section_notes: { relationships: 'RAW aggregate must never render.' }, relationships: [
    { id: 'reverse', subject_id: card.profile_id!, target_id: profileFixture.id, subject_name: 'Jordan', target_name: 'Alex', notes: 'RAW reverse analysis must never render.', label: 'colleague', revision: 1, dismissed: false, claims: [], created_at: profileFixture.updated_at, updated_at: profileFixture.updated_at },
  ] }));
  const people = screen.getAllByRole('article');
  expect(people).toHaveLength(2);
  for (const [index, expected] of [card, plain].entries()) {
    const person = within(people[index]);
    expect(person.getAllByRole('heading')).toHaveLength(1);
    expect(person.getByRole('heading', { level: 4 })).toHaveTextContent(expected.name);
    expect(people[index].querySelectorAll('.markdown-content')).toHaveLength(1);
    expect(person.getByRole('region', { name: `Relationship analysis for ${expected.name}` })).toHaveTextContent(expected.notes);
    expect(person.getAllByRole('button', { name: 'Edit relationship' })).toHaveLength(1);
    expect(person.getAllByRole('button', { name: 'Remove relationship' })).toHaveLength(1);
  }
  expect(screen.getByRole('link', { name: 'Jordan' })).toHaveAttribute('href', `/profiles/${card.profile_id}`);
  expect(within(people[1]).queryByRole('link', { name: 'Casey' })).not.toBeInTheDocument();
  expect(screen.queryByText(/RAW/)).not.toBeInTheDocument();
  expect(screen.queryByText('Saved relationship context')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: /→/ })).not.toBeInTheDocument();
});

it('uses only the selected server analysis when reciprocal API order changes', () => {
  const raw = { id: 'edge', subject_id: profileFixture.id, target_id: card.profile_id!, subject_name: 'Alex', target_name: 'Jordan', notes: 'Raw outgoing', label: '', revision: 1, dismissed: false, claims: [], created_at: profileFixture.updated_at, updated_at: profileFixture.updated_at };
  const incoming = { ...raw, id: 'reverse', subject_id: raw.target_id, target_id: raw.subject_id, notes: 'Raw incoming' };
  const { rerender } = renderWithProviders(view({ ...profileWith(), relationships: [raw, incoming] }));
  rerender(view({ ...profileWith(), relationships: [incoming, raw] }));
  expect(screen.getAllByRole('article')).toHaveLength(1);
  expect(screen.getAllByText(card.notes)).toHaveLength(1);
  expect(screen.queryByText('Raw incoming')).not.toBeInTheDocument();
  expect(screen.queryByText('Raw outgoing')).not.toBeInTheDocument();
});

it('keeps people with the same display name separate by card identity', () => {
  const secondId = 'c813c24e-e32a-4440-b6da-dfe39771bf46';
  const second = { ...card, id: `profile:${secondId}`, profile_id: secondId, notes: 'A separate person with a different relationship.' };
  renderWithProviders(view(profileWith([card, second])));
  expect(screen.getAllByRole('article')).toHaveLength(2);
  expect(screen.getAllByRole('heading', { level: 4, name: 'Jordan' })).toHaveLength(2);
  expect(screen.getAllByRole('link', { name: 'Jordan' }).map(link => link.getAttribute('href'))).toEqual([`/profiles/${card.profile_id}`, `/profiles/${secondId}`]);
  expect(screen.getAllByText(second.notes)).toHaveLength(1);
});

it('does not invent cards or an aggregate fallback when the server projects no visible relationships', () => {
  renderWithProviders(view({ ...profileWith([]), section_notes: { relationships: 'Hidden old source.' } }));
  expect(screen.queryByRole('article')).not.toBeInTheDocument();
  expect(screen.queryByText('Hidden old source.')).not.toBeInTheDocument();
  expect(screen.queryByText('Assign saved analysis')).not.toBeInTheDocument();
});

it('links evidence without rendering a second relationship or observation body', () => {
  renderWithProviders(view(profileWith()));
  expect(screen.getByRole('link', { name: 'Meeting evidence (2)' })).toHaveAttribute('href', `/profiles/${profileFixture.id}?tab=evidence&target_id=${card.profile_id}`);
  expect(screen.queryByText(profileFixture.claims[0].content)).not.toBeInTheDocument();
});

it('creates a named person without silently creating a profile', async () => {
  renderWithProviders(view(profileWith([])));
  fireEvent.click(screen.getByRole('button', { name: 'Add relationship' }));
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: ' Casey ' } });
  fireEvent.change(screen.getByLabelText('Analysis'), { target: { value: ' Values independent judgment. ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await waitFor(() => expect(api.profiles.createRelationshipCard).toHaveBeenCalledWith(profileFixture.id, { expected_revision: 1, name: 'Casey', profile_id: null, label: '', notes: 'Values independent judgment.' }));
  expect(api.profiles.create).not.toHaveBeenCalled();
  expect(reload).toHaveBeenCalled();
});

it('captures profile and selected target revisions without protecting an untouched empty analysis', async () => {
  const { rerender } = renderWithProviders(view(profileWith([])));
  fireEvent.click(screen.getByRole('button', { name: 'Add relationship' }));
  await screen.findByRole('option', { name: 'Jordan · jordan@example.test' });
  fireEvent.change(screen.getByLabelText('Linked profile'), { target: { value: other.id } });
  rerender(view({ ...profileWith([]), revision: 5 }));
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await waitFor(() => expect(api.profiles.createRelationshipCard).toHaveBeenCalledWith(profileFixture.id, { expected_revision: 1, name: 'Jordan', profile_id: other.id, target_revision: 4, label: '' }));
});

it('edits inside the same person card and sends the captured opaque version', async () => {
  const { rerender } = renderWithProviders(view(profileWith()));
  const article = screen.getByRole('article', { name: 'Relationship with Jordan' });
  fireEvent.click(within(article).getByRole('button', { name: 'Edit relationship' }));
  expect(screen.getAllByRole('article')).toHaveLength(1);
  expect(within(article).getAllByRole('heading')).toHaveLength(1);
  fireEvent.change(screen.getByLabelText('Analysis'), { target: { value: 'My revised assessment.' } });
  rerender(view(profileWith([{ ...card, version: 'b'.repeat(64) }])));
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await waitFor(() => expect(api.profiles.updateRelationshipCard).toHaveBeenCalledWith(profileFixture.id, card.id, { version: card.version, label: 'colleague', notes: 'My revised assessment.' }));
});

it('renames and optionally links an unlinked person without overwriting unchanged analysis', async () => {
  const named = { ...card, id: 'name:casey', name: 'Casey', profile_id: null };
  renderWithProviders(view(profileWith([named])));
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  await screen.findByRole('option', { name: 'Jordan · jordan@example.test' });
  fireEvent.change(screen.getByLabelText('Linked profile'), { target: { value: other.id } });
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await waitFor(() => expect(api.profiles.updateRelationshipCard).toHaveBeenCalledWith(profileFixture.id, named.id, { version: named.version, name: 'Jordan', profile_id: other.id, target_revision: 4, label: 'colleague' }));
});

it('unlinks a person explicitly and keeps their literal name', async () => {
  renderWithProviders(view(profileWith()));
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  await screen.findByRole('option', { name: 'Jordan · jordan@example.test' });
  fireEvent.change(screen.getByLabelText('Linked profile'), { target: { value: '' } });
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Jordan Rivera' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await waitFor(() => expect(api.profiles.updateRelationshipCard).toHaveBeenCalledWith(profileFixture.id, card.id, { version: card.version, name: 'Jordan Rivera', profile_id: null, label: 'colleague' }));
});

it('protects explicit clears and releases automatic updates without clearing the analysis', async () => {
  const { rerender } = renderWithProviders(view(profileWith()));
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  fireEvent.change(screen.getByLabelText('Analysis'), { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await waitFor(() => expect(api.profiles.updateRelationshipCard).toHaveBeenCalledWith(profileFixture.id, card.id, { version: card.version, label: 'colleague', notes: '' }));
  rerender(view(profileWith([{ ...card, notes: '', human: true, version: 'c'.repeat(64) }])));
  expect(screen.getByText('You have kept this analysis empty.')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Allow automatic updates' }));
  await waitFor(() => expect(api.profiles.updateRelationshipCard).toHaveBeenLastCalledWith(profileFixture.id, card.id, { version: 'c'.repeat(64), allow_agent_notes: true }));
});

it('requires confirmation and removes only the displayed card version', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
  renderWithProviders(view(profileWith()));
  fireEvent.click(screen.getByRole('button', { name: 'Remove relationship' }));
  expect(api.profiles.removeRelationshipCard).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Remove relationship' }));
  await waitFor(() => expect(api.profiles.removeRelationshipCard).toHaveBeenCalledWith(profileFixture.id, card.id, card.version));
  confirm.mockRestore();
});

it('locks the submitted fields and competing actions while a save is pending', async () => {
  let complete!: (value: ParticipantProfile) => void;
  vi.mocked(api.profiles.updateRelationshipCard).mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
  renderWithProviders(view(profileWith()));
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  expect(screen.getByLabelText('Analysis')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Add relationship' })).toBeDisabled();
  await act(async () => { complete(profileWith()); });
  expect(screen.queryByLabelText('Analysis')).not.toBeInTheDocument();
});

it('retains a conflict draft, offers refresh retry and shows current analysis before resaving', async () => {
  vi.mocked(api.profiles.updateRelationshipCard).mockRejectedValueOnce(new ApiError('Conflict', 409));
  const initial = profileWith();
  const { rerender } = renderWithProviders(view(initial));
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  fireEvent.change(screen.getByLabelText('Analysis'), { target: { value: 'My retained draft.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('button', { name: 'Save relationship' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Retry relationship refresh' }));
  expect(reload).toHaveBeenCalledTimes(2);
  expect(screen.getByLabelText('Analysis')).toHaveValue('My retained draft.');
  rerender(view(profileWith([{ ...card, version: 'b'.repeat(64), notes: 'New saved analysis.', label: 'Updated label' }])));
  expect(within(screen.getByRole('region', { name: 'Current saved analysis' })).getByText('New saved analysis.')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Save relationship' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  expect(screen.getByLabelText('Relationship label (optional)')).toHaveValue('Updated label');
  await waitFor(() => expect(api.profiles.updateRelationshipCard).toHaveBeenLastCalledWith(profileFixture.id, card.id, { version: 'b'.repeat(64), label: 'Updated label', notes: 'My retained draft.' }));
});

it('permits an unchanged-version retry only after a successful accepted reread', async () => {
  vi.mocked(api.profiles.updateRelationshipCard).mockRejectedValueOnce(new ApiError('Busy', 409));
  const initial = profileWith();
  const { rerender } = renderWithProviders(view(initial));
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('button', { name: 'Save relationship' })).toBeDisabled();
  rerender(view({ ...initial }));
  expect(screen.getByRole('button', { name: 'Save relationship' })).toBeEnabled();
});

it.each(['removed', 'source-withdrawn'])('keeps recovery and Cancel when the edited card is %s', async mode => {
  vi.mocked(api.profiles.updateRelationshipCard).mockRejectedValueOnce(new ApiError('Conflict', 409));
  const { rerender } = renderWithProviders(view(profileWith()));
  fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
  fireEvent.change(screen.getByLabelText('Analysis'), { target: { value: 'Retained privately until recovery.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save relationship' }));
  await screen.findByRole('alert');
  rerender(view(profileWith(mode === 'removed' ? [] : [{ ...card, notes: '', status: 'stale', version: 'd'.repeat(64) }])));
  expect(screen.queryByLabelText('Analysis')).not.toBeInTheDocument();
  expect(screen.queryByText(card.notes)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save relationship' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(busy).toHaveBeenLastCalledWith(false);
});

it('keeps unassigned text out of the current view and assigns it only from an explicit dialog', async () => {
  const unassigned = { notes: 'Preserved analysis that needs a person.', version: 'e'.repeat(64) };
  renderWithProviders(view({ ...profileWith([]), relationship_unassigned: unassigned }));
  expect(screen.queryByText(unassigned.notes)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Assign saved analysis' }));
  expect(screen.getByRole('dialog', { name: 'Assign saved analysis' })).toBeVisible();
  expect(screen.getByLabelText('Analysis')).toHaveValue(unassigned.notes);
  expect(screen.getByLabelText('Analysis')).toHaveAttribute('readonly');
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Casey' } });
  fireEvent.click(screen.getByRole('button', { name: 'Assign analysis' }));
  await waitFor(() => expect(api.profiles.createRelationshipCard).toHaveBeenCalledWith(profileFixture.id, { expected_revision: 1, name: 'Casey', profile_id: null, label: '', assignment_version: unassigned.version }));
  expect(api.profiles.create).not.toHaveBeenCalled();
});

it('does not permit assigning a withdrawn source and retains an accessible Cancel', () => {
  const { rerender } = renderWithProviders(view({ ...profileWith([]), relationship_unassigned: { notes: 'Withdrawn private source.', version: 'e'.repeat(64) } }));
  fireEvent.click(screen.getByRole('button', { name: 'Assign saved analysis' }));
  rerender(view(profileWith([])));
  expect(screen.queryByDisplayValue('Withdrawn private source.')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Assign analysis' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
