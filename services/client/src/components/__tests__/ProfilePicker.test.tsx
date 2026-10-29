import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { ProfilePicker } from '../ProfilePicker';
vi.mock('../../api', () => ({ api: { profiles: { list: vi.fn() } } }));
import { api } from '../../api';
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.profiles.list).mockResolvedValue({ items: [{ ...profileFixture, created_at: profileFixture.updated_at, meeting_count: 0, claim_count: 0 }], total: 1 }); });

it('searches inside an existing editor without submitting its parent form', async () => {
  const submit = vi.fn(); const select = vi.fn();
  renderWithProviders(<form onSubmit={submit}><ProfilePicker label="Find person" selectionLabel="Person" value="" onSelect={select} /></form>);
  await screen.findByRole('option', { name: 'Alex · alex@example.test' });
  fireEvent.change(screen.getByLabelText('Find person'), { target: { value: ' Alex ' } });
  fireEvent.keyDown(screen.getByLabelText('Find person'), { key: 'Enter' });
  await waitFor(() => expect(api.profiles.list).toHaveBeenLastCalledWith({ q: 'Alex', limit: 25 }));
  expect(submit).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Person'), { target: { value: profileFixture.id } });
  expect(select).toHaveBeenLastCalledWith(expect.objectContaining({ id: profileFixture.id, revision: 1 }));
});
