import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { ProfileHistory } from '../ProfileHistory';
import type { ProfileRevision } from '../../api';
import { POLL_INTERVAL_MS } from '../../constants';

vi.mock('../../api', () => ({ api: { profiles: { history: vi.fn(), historyOne: vi.fn() } } }));
import { api } from '../../api';
const revision: ProfileRevision = { id: 12, profile_id: 'person', base_revision: 2, new_revision: 3, actor: 'agent', source: 'assessment', source_id: null, input_hash: 'hash', created_at: '2026-10-29T12:00:00Z', changes: { 'section_notes.drivers': { before: 'Old assessment', after: 'New assessment' } } };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.profiles.history).mockResolvedValue({ items: [revision], total: 1 }); vi.mocked(api.profiles.historyOne).mockResolvedValue(revision); });
afterEach(() => vi.useRealTimers());

it('loads history on demand and shows automatically applied before/after changes without approval controls', async () => {
  renderWithProviders(<ProfileHistory profileId="person" revision={3} />);
  expect(api.profiles.history).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('History'));
  fireEvent.click(await screen.findByRole('button', { name: 'View change #12' }));
  expect(await screen.findByText('New assessment')).toBeInTheDocument();
  expect(screen.getByText('Old assessment')).toBeInTheDocument();
  expect(api.profiles.historyOne).toHaveBeenCalledWith('person', 12);
  expect(screen.getByText(/Automatic update/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Before' }));
  expect(screen.getByText('Old assessment')).toBeInTheDocument();
  expect(screen.queryByText('New assessment')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'After' }));
  expect(screen.getByText('New assessment')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Approve|Reject/ })).not.toBeInTheDocument();
});

it('offers read retry and gives an honest empty state', async () => {
  vi.mocked(api.profiles.history).mockRejectedValueOnce(new Error('private diagnostic')).mockResolvedValueOnce({ items: [], total: 0 });
  renderWithProviders(<ProfileHistory profileId="person" revision={3} />);
  fireEvent.click(screen.getByText('History'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load history.');
  expect(screen.queryByText('private diagnostic')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry history' }));
  expect(await screen.findByText('No changes recorded yet.')).toBeInTheDocument();
});

it('keeps the chosen revision exact when a slower prior detail request finishes', async () => {
  const next = { ...revision, id: 13, base_revision: 3, new_revision: 4, changes: { section_notes: { before: {}, after: { overview: 'Current selected change' } } } };
  vi.mocked(api.profiles.history).mockResolvedValue({ items: [next, revision], total: 2 });
  let oldComplete!: (value: ProfileRevision) => void;
  vi.mocked(api.profiles.historyOne).mockReturnValueOnce(new Promise(resolve => { oldComplete = resolve; })).mockResolvedValueOnce(next);
  renderWithProviders(<ProfileHistory profileId="person" revision={4} />);
  fireEvent.click(screen.getByText('History'));
  fireEvent.click(await screen.findByRole('button', { name: 'View change #12' }));
  fireEvent.click(screen.getByRole('button', { name: 'View change #13' }));
  expect(await screen.findByText('Current selected change')).toBeInTheDocument();
  await act(async () => oldComplete(revision));
  expect(screen.queryByText('New assessment')).not.toBeInTheDocument();
  expect(screen.getByText('Current selected change')).toBeInTheDocument();
});

it('shows readable changed sections, metadata and observation counts without proof hashes or identifiers', async () => {
  vi.mocked(api.profiles.historyOne).mockResolvedValue({ ...revision, changes: {
    section_notes: { before: { overview: 'Earlier overview', drivers: 'Unchanged' }, after: { overview: 'Updated overview', drivers: 'Unchanged' } },
    metadata: { before: { company: 'Old company' }, after: { company: 'Paralign' } },
    section_evidence: { before: {}, after: { overview: { human: false, claim_ids: ['private-claim-id'], evidence_hash: 'private-hash' } } },
    claims: { before: null, after: { added: ['private-claim-id'], changed: [], removed: [] } },
    metadata_provenance: { before: {}, after: { company: { transcript_hash: 'private-transcript-hash' } } },
  } });
  renderWithProviders(<ProfileHistory profileId="person" revision={3} />);
  fireEvent.click(screen.getByText('History'));
  fireEvent.click(await screen.findByRole('button', { name: 'View change #12' }));
  expect(await screen.findByText('Updated overview')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Company' })).toBeInTheDocument();
  expect(screen.getByText(/Observations: 1 added/)).toBeInTheDocument();
  expect(screen.queryByText(/private-/)).not.toBeInTheDocument();
  expect(screen.queryByText('Unchanged')).not.toBeInTheDocument();
});

it('refreshes the open history after a canonical revision changes', async () => {
  const { rerender } = renderWithProviders(<ProfileHistory profileId="person" revision={3} />);
  fireEvent.click(screen.getByText('History'));
  await screen.findByRole('button', { name: 'View change #12' });
  vi.mocked(api.profiles.history).mockClear();
  rerender(<ProfileHistory profileId="person" revision={4} />);
  await waitFor(() => expect(api.profiles.history).toHaveBeenCalledWith('person', { limit: 10, offset: 0 }));
});

it('shows historical relationship labels and notes as readable before/after changes', async () => {
  vi.mocked(api.profiles.historyOne).mockResolvedValue({ ...revision, changes: { relationships: {
    before: { id: 'relationship-id', label: 'Teammate', notes: 'Previous working agreement', dismissed: false },
    after: { id: 'relationship-id', label: 'Supervisor', notes: 'Current working agreement', dismissed: false },
  } } });
  renderWithProviders(<ProfileHistory profileId="person" revision={3} />);
  fireEvent.click(screen.getByText('History'));
  fireEvent.click(await screen.findByRole('button', { name: 'View change #12' }));
  expect(await screen.findByText('Current working agreement')).toBeInTheDocument();
  expect(screen.getByText('Previous working agreement')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Relationship label' })).toBeInTheDocument();
  expect(screen.getByText('Supervisor')).toBeInTheDocument();
  expect(screen.queryByText('relationship-id')).not.toBeInTheDocument();
});

it('refreshes source-projected historical text while open even without a profile revision change', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { unmount } = renderWithProviders(<ProfileHistory profileId="person" revision={3} />);
  fireEvent.click(screen.getByText('History'));
  fireEvent.click(await screen.findByRole('button', { name: 'View change #12' }));
  await screen.findByText('New assessment');
  fireEvent.click(screen.getByRole('button', { name: 'After' }));
  vi.mocked(api.profiles.historyOne).mockResolvedValue({ ...revision, source_restricted: true, changes: { section_notes: { before: {}, after: {} } } });
  await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
  await waitFor(() => expect(screen.queryByText('New assessment')).not.toBeInTheDocument());
  expect(screen.getByText(/Some generated content is hidden/)).toBeInTheDocument();
  expect(screen.queryByText(/No profile text changed/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'After' })).toHaveClass('active');
  unmount();
  vi.mocked(api.profiles.historyOne).mockClear();
  await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
  expect(api.profiles.historyOne).not.toHaveBeenCalled();
});
