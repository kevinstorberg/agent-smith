import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { profileFixture } from '../../pages/__tests__/profileFixture';
import { ProfileEvidence } from '../ProfileEvidence';
const navigation = vi.hoisted(() => ({ search: new URLSearchParams(), type: 'POP', replace: vi.fn() }));
vi.mock('react-router', async original => ({ ...await original<typeof import('react-router')>(), useSearchParams: () => [navigation.search, navigation.replace], useNavigationType: () => navigation.type }));
vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { profiles: { claims: vi.fn(), correctClaim: vi.fn() } } }));
import { api } from '../../api';
const props = { profile: profileFixture, active: true, disabled: false, onBusyChange: vi.fn(), onReload: vi.fn() };
beforeEach(() => {
  vi.clearAllMocks(); navigation.search = new URLSearchParams('tab=evidence'); navigation.type = 'POP';
  vi.mocked(api.profiles.claims).mockResolvedValue({ profile_id: profileFixture.id, revision: 1, items: profileFixture.claims, total: 1 });
});
it('keeps newer pending filters across an earlier replace commit and resets them for external navigation', async () => {
  const { rerender } = renderWithProviders(<ProfileEvidence {...props} />);
  await screen.findByText(profileFixture.claims[0].content);
  fireEvent.click(screen.getByRole('button', { name: 'Hypotheses' }));
  const first = new URLSearchParams(navigation.replace.mock.calls.at(-1)![0]);
  fireEvent.change(screen.getByLabelText('Category'), { target: { value: 'perception' } });
  act(() => { navigation.search = first; navigation.type = 'REPLACE'; rerender(<ProfileEvidence {...props} />); });
  fireEvent.change(screen.getByLabelText('Confidence'), { target: { value: 'medium' } });
  expect(Object.fromEntries(navigation.replace.mock.calls.at(-1)![0])).toEqual({ tab: 'evidence', epistemic: 'inference', category: 'perception', confidence: 'medium' });
  act(() => { navigation.search = new URLSearchParams('tab=evidence&target_id=related&status=rejected'); navigation.type = 'POP'; rerender(<ProfileEvidence {...props} />); });
  fireEvent.change(screen.getByLabelText('Category'), { target: { value: 'role' } });
  expect(Object.fromEntries(navigation.replace.mock.calls.at(-1)![0])).toEqual({ tab: 'evidence', target_id: 'related', status: 'rejected', category: 'role' });
  act(() => { navigation.search = new URLSearchParams('tab=evidence&confidence=low'); navigation.type = 'PUSH'; rerender(<ProfileEvidence {...props} />); });
  fireEvent.change(screen.getByLabelText('Review status'), { target: { value: 'active' } });
  expect(Object.fromEntries(navigation.replace.mock.calls.at(-1)![0])).toEqual({ tab: 'evidence', confidence: 'low', status: 'active' });
  await waitFor(() => expect(api.profiles.claims).toHaveBeenLastCalledWith(profileFixture.id, { limit: 20, offset: 0, sort: 'newest', confidence: 'low' }));
});

it('retains typed characters across delayed internal commits and synchronizes external query navigation', async () => {
  navigation.search = new URLSearchParams('tab=evidence&q=first');
  const { rerender } = renderWithProviders(<ProfileEvidence {...props} />);
  await screen.findByText(profileFixture.claims[0].content);
  fireEvent.change(screen.getByLabelText('Search observations'), { target: { value: 'delivery' } });
  await waitFor(() => expect(new URLSearchParams(navigation.replace.mock.calls.at(-1)?.[0]).get('q')).toBe('delivery'));
  act(() => { navigation.search = new URLSearchParams('tab=evidence&q=first'); navigation.type = 'REPLACE'; rerender(<ProfileEvidence {...props} />); });
  expect(screen.getByLabelText('Search observations')).toHaveValue('delivery');
  act(() => { navigation.search = new URLSearchParams('tab=evidence&q=%20external%20'); navigation.type = 'POP'; rerender(<ProfileEvidence {...props} />); });
  expect(screen.getByLabelText('Search observations')).toHaveValue(' external ');
  await waitFor(() => expect(api.profiles.claims).toHaveBeenLastCalledWith(profileFixture.id, { limit: 20, offset: 0, sort: 'newest', q: 'external' }));
  fireEvent.change(screen.getByLabelText('Search observations'), { target: { value: '  follow up  ' } });
  await waitFor(() => expect(new URLSearchParams(navigation.replace.mock.calls.at(-1)?.[0]).get('q')).toBe('follow up'));
  act(() => { navigation.search = new URLSearchParams(navigation.replace.mock.calls.at(-1)![0]); navigation.type = 'REPLACE'; rerender(<ProfileEvidence {...props} />); });
  await waitFor(() => expect(api.profiles.claims).toHaveBeenLastCalledWith(profileFixture.id, { limit: 20, offset: 0, sort: 'newest', q: 'follow up' }));
});

it('keeps pending text through a tab-only push and commits it into the latest tab URL', async () => {
  const { rerender } = renderWithProviders(<ProfileEvidence {...props} />);
  await screen.findByText(profileFixture.claims[0].content);
  fireEvent.change(screen.getByLabelText('Search observations'), { target: { value: 'pending query' } });
  act(() => { navigation.search = new URLSearchParams('tab=relationships'); navigation.type = 'PUSH'; rerender(<ProfileEvidence {...props} />); });
  expect(screen.getByLabelText('Search observations')).toHaveValue('pending query');
  await waitFor(() => expect(Object.fromEntries(navigation.replace.mock.calls.at(-1)?.[0] || [])).toEqual({ tab: 'relationships', q: 'pending query' }));
});

it('cancels pending text when Back changes the accepted URL while keeping the same query', async () => {
  const { rerender } = renderWithProviders(<ProfileEvidence {...props} />);
  await screen.findByText(profileFixture.claims[0].content);
  fireEvent.change(screen.getByLabelText('Search observations'), { target: { value: 'pending query' } });
  act(() => { navigation.search = new URLSearchParams('tab=relationships&confidence=low'); navigation.type = 'POP'; rerender(<ProfileEvidence {...props} />); });
  expect(screen.getByLabelText('Search observations')).toHaveValue('');
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 350)); });
  expect(navigation.replace).not.toHaveBeenCalled();
  expect(api.profiles.claims).toHaveBeenLastCalledWith(profileFixture.id, { limit: 20, offset: 0, sort: 'newest', confidence: 'low' });
});
