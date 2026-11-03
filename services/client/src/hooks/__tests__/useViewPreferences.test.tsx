import { act, renderHook } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { useViewPreferences } from '../useViewPreferences';
import type { ViewCookieStore } from '../useViewPreferences';
import { defaultView, mergeViewCookie, readViewCookie, resolveView } from '../../utils/viewPreferences';

function cookieStore(initial = '') {
  let header = initial;
  const store: ViewCookieStore = { secure: false, read: vi.fn(() => header), write: vi.fn(value => { header = value; }) };
  return { store, read: () => header, externalWrite: (value: string) => { header = value; } };
}
function router(entries = ['/jobs']) {
  return function Router({ children }: { children: ReactNode }) { return <MemoryRouter initialEntries={entries}>{children}</MemoryRouter>; };
}

describe('view preference browser adapter', () => {
  it('ignores callbacks captured for an earlier scope instead of modifying the newly mounted scope', () => {
    let cookie = mergeViewCookie('', 'jobs', { ...defaultView('jobs'), q: 'one', offset: 10 }, { scope: '1' });
    cookie = mergeViewCookie(cookie, 'jobs', { ...defaultView('jobs'), q: 'two', offset: 20 }, { scope: '2' });
    const storage = cookieStore(cookie);
    const { result, rerender } = renderHook(({ scope }) => useViewPreferences('jobs', { scope, cookieStore: storage.store }), {
      wrapper: router(), initialProps: { scope: '1' },
    });
    const oldSetField = result.current.setField;
    const oldPageChange = result.current.pagination.onPageChange!;
    const oldReset = result.current.reset;
    rerender({ scope: '2' });
    const currentCookie = storage.read();
    vi.mocked(storage.store.write).mockClear();
    act(() => { oldSetField('q', 'wrong scope'); oldPageChange({ limit: 50, offset: 100 }); oldReset(); });
    expect(result.current.values).toMatchObject({ q: 'two', limit: 10, offset: 20 });
    expect(storage.read()).toBe(currentCookie);
    expect(storage.store.write).not.toHaveBeenCalled();
  });

  it('restores a changed scope synchronously without sharing its cookie entry', () => {
    let cookie = mergeViewCookie('', 'jobs', { ...defaultView('jobs'), q: 'one', offset: 10 }, { scope: '1' });
    cookie = mergeViewCookie(cookie, 'jobs', { ...defaultView('jobs'), q: 'two', offset: 20 }, { scope: '2' });
    const storage = cookieStore(cookie);
    const { result, rerender } = renderHook(({ scope }) => useViewPreferences('jobs', { scope, cookieStore: storage.store }), {
      wrapper: router(), initialProps: { scope: '1' },
    });
    expect(result.current.values).toMatchObject({ q: 'one', offset: 10 });
    rerender({ scope: '2' });
    expect(result.current.values).toMatchObject({ q: 'two', offset: 20 });
    act(() => result.current.setField('q', 'new two'));
    expect(resolveView('jobs', storage.read(), new URLSearchParams(), '1').q).toBe('one');
    expect(resolveView('jobs', storage.read(), new URLSearchParams(), '2').q).toBe('new two');
  });

  it.each([['/missing', true], ['/jobs', false]] as const)('does not write preferences on unmatched or inactive views: %s', (path, active) => {
    const storage = cookieStore();
    const { result } = renderHook(() => useViewPreferences('jobs', { active, cookieStore: storage.store }), { wrapper: router([path]) });
    act(() => result.current.setField('q', 'ignored'));
    expect(storage.store.write).not.toHaveBeenCalled();
  });

  it('buffers rapid URL updates without dropping fields or unrelated parameters', () => {
    const storage = cookieStore();
    const { result } = renderHook(() => ({ preferences: useViewPreferences('jobs', { cookieStore: storage.store }), search: useLocation().search }), { wrapper: router(['/jobs?keep=1']) });
    act(() => { result.current.preferences.setField('q', 'rapid'); result.current.preferences.setField('sort', 'name'); });
    expect(result.current.preferences.values).toMatchObject({ q: 'rapid', sort: 'name', offset: 0 });
    const params = new URLSearchParams(result.current.search);
    expect(Object.fromEntries(params)).toMatchObject({ q: 'rapid', sort: 'name', offset: '0', keep: '1' });
    expect(readViewCookie(storage.read())[0].values).toMatchObject({ q: 'rapid', sort: 'name' });
  });

  it('honors external navigation and Back/Forward URL state over recently persisted values', () => {
    const storage = cookieStore();
    const { result } = renderHook(() => ({ preferences: useViewPreferences('jobs', { cookieStore: storage.store }), navigate: useNavigate() }), {
      wrapper: router(['/jobs?q=back&limit=10&offset=10', '/jobs?q=initial&limit=10&offset=20']),
    });
    act(() => result.current.navigate('/jobs?q=external&limit=25&offset=50'));
    expect(result.current.preferences.values).toMatchObject({ q: 'external', limit: 25, offset: 50 });
    act(() => result.current.preferences.setField('sort', 'name'));
    act(() => result.current.navigate(-1));
    expect(result.current.preferences.values).toMatchObject({ q: 'initial', offset: 20 });
    act(() => result.current.navigate(-1));
    expect(result.current.preferences.values).toMatchObject({ q: 'back', offset: 10 });
    act(() => result.current.navigate(1));
    expect(result.current.preferences.values).toMatchObject({ q: 'initial', offset: 20 });
  });

  it('rereads before merging another screen and removes oversized obsolete entries without truncating live input', () => {
    const storage = cookieStore(mergeViewCookie('', 'jobs', { ...defaultView('jobs'), q: 'obsolete' }));
    const { result } = renderHook(() => useViewPreferences('jobs', { cookieStore: storage.store }), { wrapper: router() });
    storage.externalWrite(mergeViewCookie(storage.read(), 'plans', { ...defaultView('plans'), q: 'another writer' }));
    const oversized = '🙂'.repeat(300);
    act(() => result.current.setField('q', oversized));
    expect(result.current.values.q).toBe(oversized);
    expect(readViewCookie(storage.read())).toEqual([{ key: 'plans', values: { q: 'another writer' } }]);
  });

  it('keeps live state usable when browser cookie reads and writes are denied', () => {
    const store: ViewCookieStore = { secure: false, read: () => { throw new Error('Read denied'); }, write: () => { throw new Error('Write denied'); } };
    const { result } = renderHook(() => useViewPreferences('jobs', { cookieStore: store }), { wrapper: router() });
    act(() => result.current.setField('q', 'live'));
    expect(result.current.values.q).toBe('live');
    act(() => result.current.reset());
    expect(result.current.values).toEqual(defaultView('jobs'));
  });
});
