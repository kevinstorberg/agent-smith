import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { ProfilesIndexPage } from '../ProfilesIndexPage';
import { profileFixture } from './profileFixture';
import { POLL_INTERVAL_MS } from '../../constants';
import type { ProfileSummary } from '../../api';

const navigate = vi.fn();
vi.mock('react-router', async importOriginal => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useNavigate: () => navigate };
});
vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { profiles: { list: vi.fn(), update: vi.fn() } } };
});
import { api } from '../../api';

const read = vi.mocked(api.profiles.list);
const profiles: ProfileSummary[] = [
  { ...profileFixture, created_at: '2026-10-28T12:00:00Z', claim_count: 5, meeting_count: 3 },
  { ...profileFixture, id: 'meeting-profile', display_name: 'Speaker 1', email: null, identity_scope: 'meeting',
    created_at: '2026-10-28T12:00:00Z', claim_count: 0, meeting_count: 0 },
];

beforeEach(() => {
  vi.clearAllMocks();
  read.mockResolvedValue({ items: profiles, total: 2 });
  vi.mocked(api.profiles.update).mockResolvedValue(profileFixture);
});
afterEach(() => vi.useRealTimers());

describe('ProfilesIndexPage', () => {
  it('shows cumulative profiles across identity scopes without filtering by meetings or devices', async () => {
    renderWithProviders(<ProfilesIndexPage />);
    expect(await screen.findByText('Alex')).toBeInTheDocument();
    expect(screen.getByText('alex@example.test')).toBeInTheDocument();
    expect(screen.getByText('Speaker 1')).toBeInTheDocument();
    expect(screen.getByText('Meeting only')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(read).toHaveBeenCalledWith({ limit: 10, offset: 0, q: undefined, sort: 'created_at_desc' });
  });

  it('opens the canonical detail from click or keyboard', async () => {
    renderWithProviders(<ProfilesIndexPage />);
    const name = await screen.findByText('Alex');
    fireEvent.click(name);
    expect(navigate).toHaveBeenCalledWith(`/profiles/${profileFixture.id}`);
    fireEvent.keyDown(screen.getByText('Speaker 1').closest('tr')!, { key: 'Enter' });
    expect(navigate).toHaveBeenLastCalledWith('/profiles/meeting-profile');
  });

  it('searches, pages and clears on the server while resetting the page', async () => {
    read.mockResolvedValue({ items: profiles, total: 25 });
    renderWithProviders(<ProfilesIndexPage />);
    await screen.findByText('Alex');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(read).toHaveBeenLastCalledWith({ limit: 10, offset: 10, q: undefined, sort: 'created_at_desc' }));
    fireEvent.change(screen.getByLabelText('Search profiles'), { target: { value: ' alex@example.test ' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Search' }).closest('form')!);
    await waitFor(() => expect(read).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: 'alex@example.test', sort: 'created_at_desc' }));
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() => expect(read).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: undefined, sort: 'created_at_desc' }));
  });

  it('distinguishes loading, empty profiles, and empty search results', async () => {
    read.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<ProfilesIndexPage />);
    expect(screen.getByText('Loading profiles...')).toBeInTheDocument();
    expect(await screen.findByText(/No profiles saved yet/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Search profiles'), { target: { value: 'Nobody' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Search' }).closest('form')!);
    expect(await screen.findByText('No profiles match your search.')).toBeInTheDocument();
  });

  it('shows reader failures separately from an empty list and supports retry', async () => {
    read.mockRejectedValueOnce(new Error('PRIVATE_BACKEND_DETAIL'));
    renderWithProviders(<ProfilesIndexPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load profiles. Try again.');
    expect(screen.queryByText(/PRIVATE_BACKEND_DETAIL/)).not.toBeInTheDocument();
    expect(screen.queryByText(/No profiles saved yet/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Alex')).toBeInTheDocument();
  });

  it('polls the current filtered page', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    read.mockResolvedValue({ items: profiles, total: 25 });
    renderWithProviders(<ProfilesIndexPage />);
    await screen.findByText('Alex');
    fireEvent.change(screen.getByLabelText('Search profiles'), { target: { value: 'alex' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Search' }).closest('form')!);
    await waitFor(() => expect(read).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: 'alex', sort: 'created_at_desc' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(read).toHaveBeenLastCalledWith({ limit: 10, offset: 10, q: 'alex', sort: 'created_at_desc' }));
    read.mockClear();
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    expect(read).toHaveBeenCalledWith({ limit: 10, offset: 10, q: 'alex', sort: 'created_at_desc' });
    expect(screen.queryByText('Loading profiles...')).not.toBeInTheDocument();
  });

  it('filters by all tags and stars, sorts, and resets paging', async () => {
    read.mockResolvedValue({ items: profiles, total: 25 });
    renderWithProviders(<ProfilesIndexPage />);
    await screen.findByText('Alex');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(read).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 })));
    fireEvent.change(screen.getByLabelText('Filter by tags'), { target: { value: 'team, priority,team' } });
    await waitFor(() => expect(read).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: undefined, sort: 'created_at_desc', tags: ['team', 'priority'] }));
    fireEvent.click(screen.getByLabelText('Starred only'));
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'name_asc' } });
    await waitFor(() => expect(read).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: undefined, sort: 'name_asc', tags: ['team', 'priority'], starred: true }));
  });

  it('stars a profile using its revision without activating row navigation', async () => {
    renderWithProviders(<ProfilesIndexPage />);
    const button = await screen.findByRole('button', { name: 'Star Alex' });
    fireEvent.keyDown(button, { key: 'Enter' });
    fireEvent.click(button);
    await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith(profileFixture.id, { expected_revision: 1, starred: true }));
    expect(navigate).not.toHaveBeenCalled();
  });
});
