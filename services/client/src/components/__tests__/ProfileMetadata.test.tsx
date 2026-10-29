import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { ProfileMetadata } from '../ProfileMetadata';

vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { profiles: { update: vi.fn() } } };
});
import { api, ApiError } from '../../api';
const reload = vi.fn();
const busy = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.profiles.update).mockResolvedValue(profileFixture);
});

describe('ProfileMetadata', () => {
  it('saves normalized tags and a star with the captured revision', async () => {
    renderWithProviders(<ProfileMetadata profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit tags and star' }));
    fireEvent.change(screen.getByLabelText('Tags'), { target: { value: ' team, priority,team , ' } });
    fireEvent.click(screen.getByLabelText('Starred'));
    fireEvent.click(screen.getByRole('button', { name: 'Save tags and star' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenCalledWith(profileFixture.id, { expected_revision: 1, tags: ['team', 'priority'], starred: true }));
    expect(reload).toHaveBeenCalled();
  });

  it('preserves a metadata draft across a conflict and requires an explicit retry', async () => {
    vi.mocked(api.profiles.update).mockRejectedValueOnce(new ApiError('Private detail', 409));
    const { rerender } = renderWithProviders(<ProfileMetadata profile={profileFixture} disabled={false} onBusyChange={busy} onReload={reload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit tags and star' }));
    fireEvent.change(screen.getByLabelText('Tags'), { target: { value: 'my draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save tags and star' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Review the latest version and save again.');
    rerender(<ProfileMetadata profile={{ ...profileFixture, revision: 2 }} disabled={false} onBusyChange={busy} onReload={reload} />);
    expect(screen.getByLabelText('Tags')).toHaveValue('my draft');
    fireEvent.click(screen.getByRole('button', { name: 'Save tags and star' }));
    await waitFor(() => expect(api.profiles.update).toHaveBeenLastCalledWith(profileFixture.id, { expected_revision: 2, tags: ['my draft'], starred: false }));
  });
});
