import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useLocation } from 'react-router';
import { renderWithProviders } from '../../test-utils';
import { JobsIndexPage } from '../JobsIndexPage';
import { PlansIndexPage } from '../PlansIndexPage';
import { api } from '../../api';
import { defaultView, mergeViewCookie, readViewCookie } from '../../utils/viewPreferences';

vi.mock('../../api', () => ({ api: { jobs: { list: vi.fn(), setScheduling: vi.fn() }, plans: { list: vi.fn() } } }));

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.mocked(api.jobs.list).mockResolvedValue({ items: [], total: 100 });
  vi.mocked(api.plans.list).mockResolvedValue({ items: [], total: 100 });
});
afterEach(() => { vi.restoreAllMocks(); document.cookie = 'existing-session=; Path=/; Max-Age=0'; vi.useRealTimers(); });

function Location() { const location = useLocation(); return <output aria-label="URL search">{location.search}</output>; }

describe('saved list preferences reach the API boundary', () => {
  it.each([
    { kind: 'ASCII', query: 'x'.repeat(1200) },
    { kind: 'multibyte Unicode', query: '漢字🙂'.repeat(300) },
  ])('preserves oversized live $kind search text and URL while removing its obsolete saved query', async ({ query }) => {
    vi.useFakeTimers();
    document.cookie = mergeViewCookie('', 'jobs', { ...defaultView('jobs'), q: 'obsolete' });
    renderWithProviders(<><JobsIndexPage /><Location /></>, { initialEntries: ['/jobs'] });
    await act(async () => {});
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), { target: { value: query } });
    expect(screen.getByRole('textbox', { name: 'Search' })).toHaveValue(query);
    expect(new URLSearchParams(screen.getByLabelText('URL search').textContent || '').get('q')).toBe(query);
    expect(readViewCookie(document.cookie)).toEqual([]);
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(api.jobs.list).toHaveBeenLastCalledWith(expect.objectContaining({ q: query }));
  });

  it('restores Plans criteria and page on its first request without inheriting Jobs settings', async () => {
    let cookie = mergeViewCookie('', 'jobs', { ...defaultView('jobs'), q: 'unrelated', limit: 10, offset: 10 });
    cookie = mergeViewCookie(cookie, 'plans', { ...defaultView('plans'), q: 'release', project: 'agent-smith', status: 'draft', sort: 'title', limit: 50, offset: 50 });
    document.cookie = cookie;
    renderWithProviders(<PlansIndexPage />, { initialEntries: ['/plans'] });
    await waitFor(() => expect(api.plans.list).toHaveBeenCalledTimes(1));
    expect(api.plans.list).toHaveBeenCalledWith({ q: 'release', project: 'agent-smith', status: 'draft', sort: 'title', limit: 50, offset: 50 });
    expect(screen.getByRole('textbox', { name: 'Search plans' })).toHaveValue('release');
    expect(screen.getByRole('textbox', { name: 'Project scope' })).toHaveValue('agent-smith');
  });

  it('restores Jobs search, filter, sort and page before its first request', async () => {
    document.cookie = mergeViewCookie('', 'jobs', { ...defaultView('jobs'), q: 'backup', schedule_enabled: 'false', sort: 'name', limit: 25, offset: 50 });
    renderWithProviders(<JobsIndexPage />, { initialEntries: ['/jobs'] });
    await waitFor(() => expect(api.jobs.list).toHaveBeenCalledTimes(1));
    expect(api.jobs.list).toHaveBeenCalledWith({ q: 'backup', schedule_enabled: false, sort: 'name', limit: 25, offset: 50 });
    expect(screen.getByRole('textbox', { name: 'Search' })).toHaveValue('backup');
  });

  it('uses explicit URL values and clears over saved values while preserving unrelated URL parameters', async () => {
    document.cookie = mergeViewCookie('', 'jobs', { ...defaultView('jobs'), q: 'old', schedule_enabled: 'false', sort: 'name', limit: 25, offset: 50 });
    renderWithProviders(<><JobsIndexPage /><Location /></>, { initialEntries: ['/jobs?q=&sort=invalid&limit=999&keep=1'] });
    await waitFor(() => expect(api.jobs.list).toHaveBeenCalledTimes(1));
    expect(api.jobs.list).toHaveBeenLastCalledWith({ q: undefined, schedule_enabled: false, sort: 'updated', limit: 10, offset: 0 });
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort jobs' }), { target: { value: 'newest' } });
    expect(screen.getByLabelText('URL search')).toHaveTextContent('keep=1');
  });

  it('waits for the restored request before clamping against its returned total, including deletion to zero', async () => {
    let finish!: (value: { items: []; total: number }) => void;
    vi.mocked(api.jobs.list).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    document.cookie = mergeViewCookie('', 'jobs', { ...defaultView('jobs'), limit: 25, offset: 50 });
    renderWithProviders(<JobsIndexPage />, { initialEntries: ['/jobs'] });
    expect(api.jobs.list).toHaveBeenCalledTimes(1);
    expect(api.jobs.list).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 25, offset: 50 }));
    await act(async () => { finish({ items: [], total: 0 }); });
    await waitFor(() => expect(api.jobs.list).toHaveBeenCalledTimes(2));
    expect(api.jobs.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }));
    expect(readViewCookie(document.cookie)[0].values).toEqual({ limit: 25 });
  });

  it('updates only this view while retaining another screen and live controls when cookies are blocked', async () => {
    document.cookie = 'existing-session=keep; Path=/';
    let cookie = mergeViewCookie('', 'jobs', { ...defaultView('jobs'), sort: 'name', limit: 25, offset: 25 });
    cookie = mergeViewCookie(cookie, 'plans', { ...defaultView('plans'), q: 'keep' });
    document.cookie = cookie;
    renderWithProviders(<JobsIndexPage />, { initialEntries: ['/jobs'] });
    await waitFor(() => expect(api.jobs.list).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort jobs' }), { target: { value: 'updated' } });
    await waitFor(() => expect(api.jobs.list).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'updated', limit: 25, offset: 0 })));
    expect(readViewCookie(document.cookie)).toEqual([{ key: 'jobs', values: { limit: 25 } }, { key: 'plans', values: { q: 'keep' } }]);
    expect(document.cookie).toContain('existing-session=keep');
    vi.spyOn(document, 'cookie', 'set').mockImplementation(() => { throw new DOMException('Blocked', 'SecurityError'); });
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort jobs' }), { target: { value: 'newest' } });
    await waitFor(() => expect(api.jobs.list).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'newest' })));
  });
});
