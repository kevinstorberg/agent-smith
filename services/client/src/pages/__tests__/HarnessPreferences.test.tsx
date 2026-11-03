import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useLocation } from 'react-router';
import { renderWithProviders } from '../../test-utils';
import { HarnessIndexPage } from '../HarnessIndexPage';
import { api } from '../../api';
import { defaultView, harnessViewKey, mergeViewCookie, readViewCookie } from '../../utils/viewPreferences';

vi.mock('../../api', () => ({ api: { harness: { items: { list: vi.fn(), updateMetadata: vi.fn(), reorder: vi.fn() } } } }));
beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.mocked(api.harness.items.list).mockResolvedValue({ items: [], total: 100 });
});
afterEach(() => vi.useRealTimers());

function Location() { return <output aria-label="URL search">{useLocation().search}</output>; }

describe('Harness preference consumers', () => {
  it.each([['rule', 'rules'], ['skill', 'skills'], ['tool', 'tools'], ['hook', 'hooks'], ['agent', 'agents']])('restores %s settings before the first request without resetting them on mount', async (type, plural) => {
    const key = harnessViewKey(type);
    document.cookie = mergeViewCookie('', key, { ...defaultView(key), name: 'saved name', project: 'repo', sort: 'name', limit: 25, offset: 50 });
    renderWithProviders(<HarnessIndexPage type={type} />, { initialEntries: [`/harness/${plural}`] });
    await waitFor(() => expect(api.harness.items.list).toHaveBeenCalledTimes(1));
    expect(api.harness.items.list).toHaveBeenCalledWith(type, { name: 'saved name', project: 'repo', sort: 'name', limit: 25, offset: 50 });
    expect(screen.getByRole('textbox', { name: 'Search' })).toHaveValue('saved name');
  });

  it('keeps Harness name/project URL keys, debounces from the restored page and updates only the active resource', async () => {
    vi.useFakeTimers();
    let cookie = mergeViewCookie('', 'harness.tool', { ...defaultView('harness.tool'), name: 'other kind' });
    cookie = mergeViewCookie(cookie, 'harness.rule', { ...defaultView('harness.rule'), name: 'old', sort: 'name', limit: 25, offset: 50 });
    document.cookie = cookie;
    renderWithProviders(<><HarnessIndexPage type="rule" /><Location /></>, { initialEntries: ['/harness/rules?keep=1'] });
    await act(async () => {});
    vi.mocked(api.harness.items.list).mockClear();
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), { target: { value: 'new' } });
    expect(api.harness.items.list).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(api.harness.items.list).toHaveBeenLastCalledWith('rule', expect.objectContaining({ name: 'new', offset: 0 }));
    const params = new URLSearchParams(screen.getByLabelText('URL search').textContent || '');
    expect(params.get('name')).toBe('new');
    expect(params.has('q')).toBe(false);
    expect(params.get('keep')).toBe('1');
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort' }), { target: { value: 'manual' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(api.harness.items.list).toHaveBeenLastCalledWith('rule', { name: 'new', project: undefined, sort: 'manual', limit: 25, offset: 0 });
    expect(readViewCookie(document.cookie)).toEqual([{ key: 'harness.rule', values: { name: 'new', limit: 25 } }, { key: 'harness.tool', values: { name: 'other kind' } }]);
  });
});
