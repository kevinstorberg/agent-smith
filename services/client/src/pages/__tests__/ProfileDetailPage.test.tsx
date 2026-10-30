import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useLocation } from 'react-router';
import { renderWithProviders } from '../../test-utils';
import { ProfileDetailPage } from '../ProfileDetailPage';
import { metadataOptionsFixture, profileFixture, relationshipCardFixture } from './profileFixture';
import type { ParticipantProfile } from '../../api';
import { POLL_INTERVAL_MS } from '../../constants';

const navigate = vi.fn();
vi.mock('react-router', async importOriginal => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useParams: () => ({ id: profileFixture.id }), useNavigate: () => navigate };
});
vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { profiles: { get: vi.fn(), claims: vi.fn(), correctClaim: vi.fn(), remove: vi.fn(), update: vi.fn(), list: vi.fn(), merge: vi.fn(), linkEmail: vi.fn(), rebuild: vi.fn(), history: vi.fn(), historyOne: vi.fn(), createRelationshipCard: vi.fn(), updateRelationshipCard: vi.fn(), removeRelationshipCard: vi.fn(), metadataOptions: vi.fn() } } };
});
import { api, ApiError } from '../../api';

const compact: ParticipantProfile = { ...profileFixture, claims: [], claim_count: 1, meeting_count: 1, evidence_loaded: false,
  section_notes: { overview: 'Alex combines product planning with careful follow-through.', strengths: 'Builds clarity for the team.' } };
const card = { ...relationshipCardFixture, notes: 'Shared project context' };
const read = vi.mocked(api.profiles.get);
const claims = vi.mocked(api.profiles.claims);
function Location() { return <output data-testid="location">{useLocation().search}</output>; }
function renderPage(tab?: string) {
  return renderWithProviders(<><ProfileDetailPage /><Location /></>, { initialEntries: [`/profiles/${profileFixture.id}${tab ? `?tab=${tab}` : ''}`] });
}
const open = async (label: string) => fireEvent.click(await screen.findByRole('link', { name: label }));
beforeEach(() => {
  vi.clearAllMocks();
  read.mockResolvedValue(compact);
  vi.mocked(api.profiles.metadataOptions).mockResolvedValue(metadataOptionsFixture);
  claims.mockResolvedValue({ profile_id: compact.id, revision: 1, items: profileFixture.claims, total: 1 });
  vi.mocked(api.profiles.update).mockResolvedValue(compact);
  vi.mocked(api.profiles.correctClaim).mockResolvedValue(compact);
  vi.mocked(api.profiles.remove).mockResolvedValue({ deleted: true, id: compact.id });
  vi.mocked(api.profiles.list).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.profiles.history).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.profiles.updateRelationshipCard).mockResolvedValue(compact);
});
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe('ProfileDetailPage', () => {
  it('defaults to Overview with every metadata field visible and no evidence request', async () => {
    renderPage();
    expect(await screen.findByText(compact.section_notes!.overview!)).toBeVisible();
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
    for (const label of ['Gender', 'Marital status', 'Company', 'Job role / title', 'Start date', 'Supervisor', 'Other', 'Nicknames']) expect(screen.getByText(label)).toBeVisible();
    expect(screen.getAllByText('Not set')).toHaveLength(8);
    expect(screen.queryByText(profileFixture.claims[0].content)).not.toBeInTheDocument();
    expect(screen.getByText('Builds clarity for the team.')).not.toBeVisible();
    expect(claims).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Edit overview' }));
    expect(screen.getByRole('button', { name: 'Refresh assessment' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Edit' })).toBeDisabled();
  });

  it('shows one relationship card and retains its edit across tabs without rendering combined analysis', async () => {
    read.mockResolvedValue({ ...compact, relationship_cards: [card], section_notes: { ...compact.section_notes, relationships: 'Previous combined assessment.' } });
    renderPage('assessment');
    await screen.findByRole('heading', { name: 'Strengths' });
    expect(screen.getAllByRole('heading', { level: 3 })).toHaveLength(4);
    expect(screen.queryByText('Previous combined assessment.')).not.toBeInTheDocument();
    await open('Relationships');
    const relations = within(screen.getByRole('region', { name: 'Profile relationships' }));
    expect(relations.getByText(card.notes)).toBeVisible();
    expect(relations.getByRole('link', { name: 'Jordan' })).toHaveAttribute('href', `/profiles/${card.profile_id}`);
    expect(relations.getByRole('button', { name: 'Edit relationship' })).toBeVisible();
    expect(relations.queryByText('Previous combined assessment.')).not.toBeInTheDocument();
    expect(relations.queryByText('Saved relationship context')).not.toBeInTheDocument();
    fireEvent.click(relations.getByRole('button', { name: 'Edit relationship' }));
    fireEvent.change(relations.getByLabelText('Analysis'), { target: { value: 'Retained relationship draft.' } });
    expect(relations.getAllByRole('article')).toHaveLength(1);
    expect(within(relations.getByRole('article')).getAllByRole('heading')).toHaveLength(1);
    expect(claims).not.toHaveBeenCalled();
    await open('Overview');
    expect(screen.getByRole('button', { name: 'Edit' })).toBeDisabled();
    await open('Relationships');
    expect(relations.getByLabelText('Analysis')).toHaveValue('Retained relationship draft.');
    fireEvent.click(relations.getByRole('button', { name: 'Cancel' }));
    await open('Overview');
    fireEvent.click(screen.getByText('History'));
    fireEvent.click(await screen.findByText('Previous combined relationship assessment'));
    expect(within(screen.getByText('History').closest('details')!).getByText('Previous combined assessment.')).toBeVisible();
  });

  it('loads evidence lazily in fixed pages of 20 and uses URL navigation', async () => {
    const items = Array.from({ length: 45 }, (_, index) => ({ ...profileFixture.claims[0], id: `claim-${index}`, content: `Saved observation ${index + 1}` }));
    claims.mockImplementation(async (_, params) => ({ profile_id: compact.id, revision: 1, items: items.slice(params!.offset!, params!.offset! + params!.limit!), total: items.length }));
    renderPage();
    await open('Assessment');
    expect(claims).not.toHaveBeenCalled();
    await open('Evidence');
    expect(await screen.findByText('Saved observation 20')).toBeVisible();
    expect(claims).toHaveBeenCalledTimes(1);
    expect(claims).toHaveBeenLastCalledWith(compact.id, { limit: 20, offset: 0, sort: 'newest' });
    expect(screen.queryByText('Saved observation 21')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('Saved observation 21')).toBeVisible();
    expect(claims).toHaveBeenLastCalledWith(compact.id, { limit: 20, offset: 20, sort: 'newest' });
    expect(screen.getAllByRole('combobox')).toHaveLength(4);
    expect(screen.getByTestId('location')).toHaveTextContent('?tab=evidence');
  });

  it('global Edit opens Overview and retains its draft while switching views', async () => {
    renderPage('assessment');
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    expect(screen.getByTestId('location')).toHaveTextContent('?tab=overview');
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Alex Morgan' } });
    await open('Assessment');
    expect(screen.getByLabelText('Name')).not.toBeVisible();
    await open('Overview');
    expect(screen.getByLabelText('Name')).toHaveValue('Alex Morgan');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith(compact.id, { expected_revision: 1, display_name: 'Alex Morgan', tags: [], starred: false }));
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
  });

  it('retains an assessment draft across views and prevents competing relationship changes', async () => {
    read.mockResolvedValue({ ...compact, relationship_cards: [card] });
    renderPage('assessment');
    fireEvent.click(await screen.findByRole('button', { name: 'Edit strengths' }));
    fireEvent.change(screen.getByLabelText('Strengths'), { target: { value: 'My assessment draft' } });
    await open('Relationships');
    expect(screen.getByRole('button', { name: 'Add relationship' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Edit relationship' })).toBeDisabled();
    await open('Assessment');
    expect(screen.getByLabelText('Strengths')).toHaveValue('My assessment draft');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await open('Relationships');
    fireEvent.click(screen.getByRole('button', { name: 'Edit relationship' }));
    await open('Overview');
    await open('Relationships');
    expect(screen.getByLabelText('Analysis')).toHaveValue(card.notes);
    expect(screen.getByRole('button', { name: 'Refresh assessment' })).toBeDisabled();
  });

  it('retains a note draft when its conflict refresh fails and recovers without remounting', async () => {
    let failRefresh!: (error: Error) => void;
    read.mockResolvedValueOnce(compact).mockReturnValueOnce(new Promise((_, reject) => { failRefresh = reject; }));
    vi.mocked(api.profiles.update).mockRejectedValueOnce(new ApiError('Changed profile', 409));
    renderPage('assessment');
    fireEvent.click(await screen.findByRole('button', { name: 'Edit strengths' }));
    fireEvent.change(screen.getByLabelText('Strengths'), { target: { value: 'Keep this human note.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save section' }));
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    await act(async () => failRefresh(new Error('Temporary failure')));
    expect(await screen.findByText(/Could not refresh this profile/)).toBeVisible();
    expect(screen.getByLabelText('Strengths')).toHaveValue('Keep this human note.');
    read.mockResolvedValue({ ...compact, revision: 2 });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('Revision 2');
    fireEvent.click(screen.getByRole('button', { name: 'Save section' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenLastCalledWith(compact.id, { expected_revision: 2, section_notes: { strengths: 'Keep this human note.' } }));
  });

  it('history evidence links activate the Evidence view', async () => {
    const change = { id: 7, profile_id: compact.id, base_revision: 1, new_revision: 2, actor: 'agent' as const, source: 'meeting' as const, source_id: 'meeting', input_hash: null, changes: { claims: { before: [], after: ['claim'] } }, created_at: compact.updated_at };
    vi.mocked(api.profiles.history).mockResolvedValue({ items: [change], total: 1 });
    vi.mocked(api.profiles.historyOne).mockResolvedValue(change);
    renderPage();
    fireEvent.click(await screen.findByText('History'));
    fireEvent.click(await screen.findByRole('button', { name: 'View change #7' }));
    await open('View supporting evidence');
    expect(await screen.findByRole('region', { name: 'Evidence and observations' })).toBeVisible();
    expect(screen.getByTestId('location')).toHaveTextContent('?tab=evidence');
    expect(claims).toHaveBeenCalledWith(compact.id, { limit: 20, offset: 0, sort: 'newest' });
  });

  it('suppresses metadata quotes outside Evidence while keeping its source link', async () => {
    read.mockResolvedValue({ ...compact, metadata: { company: 'Paralign' }, metadata_provenance: { company: { meeting_id: 'meeting-source', transcript_hash: 'hash', participants_revision: 0, evidence: [{ segment_id: 'segment', quote: 'Private source quote.' }] } } });
    renderPage();
    expect(await screen.findByRole('link', { name: 'View source meeting' })).toHaveAttribute('href', '/meetings/meeting-source#meeting-transcript');
    expect(screen.queryByText('Private source quote.')).not.toBeInTheDocument();
    expect(claims).not.toHaveBeenCalled();
  });

  it('explains manual and meeting-only identities without claiming unavailable evidence', async () => {
    read.mockResolvedValue({ ...compact, email: null, identity_scope: 'manual' });
    renderPage();
    expect(await screen.findByText(/Manually created profile/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Add email' })).toBeVisible();
    expect(screen.queryByText(/No meeting evidence yet/)).not.toBeInTheDocument();
  });

  it('confirms deletion using the visible revision', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderPage();
    const button = await screen.findByRole('button', { name: 'Delete' });
    fireEvent.click(button);
    expect(api.profiles.remove).not.toHaveBeenCalled();
    fireEvent.click(button);
    await waitFor(() => expect(api.profiles.remove).toHaveBeenCalledWith(compact.id, 1));
    expect(navigate).toHaveBeenCalledWith('/profiles');
    confirm.mockRestore();
  });

  it('keeps failures generic and offers navigation for unavailable profiles', async () => {
    read.mockRejectedValue(new Error('PRIVATE_PROFILE_DETAIL'));
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent('It may be unavailable or deleted.');
    expect(screen.queryByText(/PRIVATE_PROFILE_DETAIL/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Back to profiles/ }));
    expect(navigate).toHaveBeenCalledWith('/profiles');
  });

  it('polls the compact profile without mounting Evidence or hiding the current content', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let finishPoll!: (profile: ParticipantProfile) => void;
    read.mockResolvedValueOnce(compact).mockReturnValueOnce(new Promise(resolve => { finishPoll = resolve; }));
    renderPage();
    await screen.findByText('Revision 1');
    await act(async () => vi.advanceTimersByTime(POLL_INTERVAL_MS));
    expect(screen.getByRole('heading', { name: 'Alex' })).toBeVisible();
    expect(screen.queryByText('Loading participant profile...')).not.toBeInTheDocument();
    await act(async () => finishPoll({ ...compact, revision: 2 }));
    expect(await screen.findByText('Revision 2')).toBeVisible();
    expect(claims).not.toHaveBeenCalled();
  });

  it('preserves the selected query view when resolving a canonical alias', async () => {
    read.mockResolvedValue({ ...compact, id: 'canonical-profile' });
    renderPage('assessment');
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/profiles/canonical-profile?tab=assessment', { replace: true }));
    await open('Overview');
    fireEvent.click(screen.getByRole('button', { name: 'Star Alex' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith('canonical-profile', { expected_revision: 1, starred: true }));
  });
});
