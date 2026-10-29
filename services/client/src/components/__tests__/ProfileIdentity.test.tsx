import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { ProfileIdentity } from '../ProfileIdentity';
import type { ProfileSummary } from '../../api';

vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { profiles: { list: vi.fn(), merge: vi.fn(), linkEmail: vi.fn() } } };
});
import { api, ApiError } from '../../api';

const target: ProfileSummary = { ...profileFixture, id: 'target-profile', display_name: 'Jordan', email: 'jordan@example.test', revision: 4,
  created_at: profileFixture.updated_at, claim_count: 2, meeting_count: 2 };
const saved = vi.fn();
const reload = vi.fn();
const busy = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.profiles.list).mockResolvedValue({ items: [target], total: 1 });
  vi.mocked(api.profiles.merge).mockResolvedValue({ ...profileFixture, ...target });
  vi.mocked(api.profiles.linkEmail).mockResolvedValue(profileFixture);
});
afterEach(() => vi.restoreAllMocks());

describe('ProfileIdentity', () => {
  it('searches merge targets and confirms both profiles before submitting their revisions', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderWithProviders(<ProfileIdentity profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} onSaved={saved} />);
    fireEvent.click(screen.getByRole('button', { name: 'Merge profile' }));
    await screen.findByRole('option', { name: 'Jordan · jordan@example.test' });
    fireEvent.change(screen.getByLabelText('Find merge target'), { target: { value: ' Jordan ' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Find profiles' }).closest('form')!);
    await waitFor(() => expect(api.profiles.list).toHaveBeenLastCalledWith({ q: 'Jordan', limit: 25 }));
    fireEvent.change(screen.getByLabelText('Keep this profile'), { target: { value: target.id } });
    fireEvent.click(screen.getByRole('button', { name: 'Merge into selected profile' }));
    expect(api.profiles.merge).not.toHaveBeenCalled();
    expect(confirm.mock.calls[0][0]).toContain('Alex');
    expect(confirm.mock.calls[0][0]).toContain('Jordan');
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'Merge into selected profile' }));
    await waitFor(() => expect(api.profiles.merge).toHaveBeenCalledWith(profileFixture.id, { target_id: target.id, expected_revision: 1, target_revision: 4 }));
    expect(saved).toHaveBeenCalledWith(expect.objectContaining({ id: target.id }));
  });

  it('keeps the selected identity after409 and uses refreshed revisions only on explicit retry', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(api.profiles.merge).mockRejectedValueOnce(new ApiError('Private conflict', 409));
    const props = { disabled: false, onBusyChange: busy, onReload: reload, onSaved: saved };
    const { rerender } = renderWithProviders(<ProfileIdentity profile={profileFixture} {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Merge profile' }));
    await screen.findByRole('option', { name: 'Jordan · jordan@example.test' });
    fireEvent.change(screen.getByLabelText('Keep this profile'), { target: { value: target.id } });
    vi.mocked(api.profiles.list).mockResolvedValue({ items: [{ ...target, revision: 5 }], total: 1 });
    fireEvent.click(screen.getByRole('button', { name: 'Merge into selected profile' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Review the refreshed profiles and try again.');
    rerender(<ProfileIdentity profile={{ ...profileFixture, revision: 2 }} {...props} />);
    await waitFor(() => expect(screen.getByLabelText('Keep this profile')).not.toBeDisabled());
    expect(screen.getByLabelText('Keep this profile')).toHaveValue(target.id);
    fireEvent.click(screen.getByRole('button', { name: 'Merge into selected profile' }));
    await waitFor(() => expect(api.profiles.merge).toHaveBeenLastCalledWith(profileFixture.id, { target_id: target.id, expected_revision: 2, target_revision: 5 }));
  });

  it('links a user-provided known email without guessing from a speaker name', async () => {
    renderWithProviders(<ProfileIdentity profile={{ ...profileFixture, identity_scope: 'meeting', email: null }} disabled={false}
      onBusyChange={busy} onReload={reload} onSaved={saved} />);
    fireEvent.click(screen.getByRole('button', { name: 'Link known email' }));
    fireEvent.change(screen.getByLabelText('Known email'), { target: { value: 'known@example.test' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Link email' }).closest('form')!);
    await waitFor(() => expect(api.profiles.linkEmail).toHaveBeenCalledWith(profileFixture.id, { email: 'known@example.test', expected_revision: 1 }));
    expect(api.profiles.list).not.toHaveBeenCalled();
  });

  it('preserves a known-email conflict and advises explicit merge without merging automatically', async () => {
    const detail = 'This email belongs to another or deleted profile; merge existing profiles instead of linking it';
    vi.mocked(api.profiles.linkEmail).mockRejectedValueOnce(new ApiError(detail, 409));
    renderWithProviders(<ProfileIdentity profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} onSaved={saved} />);
    fireEvent.click(screen.getByRole('button', { name: 'Link known email' }));
    fireEvent.change(screen.getByLabelText('Known email'), { target: { value: 'existing@example.test' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Link email' }).closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent(detail);
    expect(screen.getByLabelText('Known email')).toHaveValue('existing@example.test');
    expect(api.profiles.merge).not.toHaveBeenCalled();
  });
});
