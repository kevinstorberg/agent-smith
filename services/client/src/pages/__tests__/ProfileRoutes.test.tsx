import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router';
import App from '../../App';
import { profileFixture } from './profileFixture';
import type { ParticipantProfile, ProfileSummary } from '../../api';

vi.mock('../../components/Sidebar', () => ({ Sidebar: () => null }));
vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { ...actual.api, profiles: {
    get: vi.fn(), list: vi.fn(), merge: vi.fn(), linkEmail: vi.fn(), update: vi.fn(), correctClaim: vi.fn(), remove: vi.fn(),
  } } };
});
import { api } from '../../api';

const winner: ParticipantProfile = { ...profileFixture, id: '8a1f4452-c460-43e8-9e90-515bdcb94c6d', display_name: 'Jordan', email: 'jordan@example.test', revision: 4 };
const target: ProfileSummary = { ...winner, created_at: winner.updated_at, meeting_count: 1, claim_count: 1 };

function LocationProbe() {
  const { pathname } = useLocation();
  return <output data-testid="profile-location">{pathname}</output>;
}

function renderProfile() {
  return render(<MemoryRouter initialEntries={[`/profiles/${profileFixture.id}`]}><App /><LocationProbe /></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.profiles.get).mockImplementation(async id => id === profileFixture.id ? profileFixture : winner);
  vi.mocked(api.profiles.list).mockResolvedValue({ items: [target], total: 1 });
  vi.mocked(api.profiles.merge).mockResolvedValue(winner);
});
afterEach(() => vi.restoreAllMocks());

describe('Profile route transitions', () => {
  it('stays on the merge winner instead of redirecting back from retained source data', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderProfile();
    await screen.findByRole('heading', { name: 'Alex' });
    fireEvent.click(screen.getByRole('button', { name: 'Merge profile' }));
    await screen.findByRole('option', { name: 'Jordan · jordan@example.test' });
    fireEvent.change(screen.getByLabelText('Keep this profile'), { target: { value: winner.id } });
    fireEvent.click(screen.getByRole('button', { name: 'Merge into selected profile' }));

    expect(await screen.findByRole('heading', { name: 'Jordan' })).toBeInTheDocument();
    expect(screen.getByTestId('profile-location')).toHaveTextContent(`/profiles/${winner.id}`);
    expect(vi.mocked(api.profiles.get).mock.calls.map(([id]) => id)).toEqual([profileFixture.id, winner.id]);
  });

  it('resolves a bookmarked merged identity to a fresh canonical profile route', async () => {
    vi.mocked(api.profiles.get).mockResolvedValue(winner);
    renderProfile();

    await waitFor(() => expect(screen.getByTestId('profile-location')).toHaveTextContent(`/profiles/${winner.id}`));
    expect(await screen.findByRole('heading', { name: 'Jordan' })).toBeInTheDocument();
    expect(vi.mocked(api.profiles.get).mock.calls.map(([id]) => id)).toEqual([profileFixture.id, winner.id]);
  });
});
