import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useNavigate } from 'react-router';
import { renderWithProviders } from '../../test-utils';
import { MemoryPage } from '../MemoryPage';
import { api } from '../../api';
import { defaultView, mergeViewCookie, readViewCookie } from '../../utils/viewPreferences';

vi.mock('../../api', () => ({ api: { memory: { list: vi.fn(), search: vi.fn(), update: vi.fn(), remove: vi.fn() } } }));
beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.mocked(api.memory.list).mockResolvedValue({ items: [], total: 100 });
  vi.mocked(api.memory.search).mockResolvedValue({ items: [], total: 100 });
});
afterEach(() => vi.useRealTimers());

describe('Memory preferences', () => {
  it('honors an explicit URL clear even when the applied query was already empty and only a local draft differs', async () => {
    vi.useFakeTimers();
    function ClearURL() {
      const navigate = useNavigate();
      return <button onClick={() => navigate('/memory?q=')}>Clear through URL</button>;
    }
    renderWithProviders(<><MemoryPage /><ClearURL /></>, { initialEntries: ['/memory'] });
    await act(async () => {});
    fireEvent.change(screen.getByRole('textbox', { name: 'Search memories' }), { target: { value: 'unapplied draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Clear through URL' }));
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(screen.getByRole('textbox', { name: 'Search memories' })).toHaveValue('');
    expect(api.memory.search).not.toHaveBeenCalled();
    expect(readViewCookie(document.cookie)).toEqual([]);
  });

  it('consumes external URL navigation and clears immediately without letting an older draft or debounce restore itself', async () => {
    vi.useFakeTimers();
    function NavigateViews() {
      const navigate = useNavigate();
      return <><button onClick={() => navigate('/memory?q=external&meeting_only=true&limit=25&offset=50')}>External view</button>
        <button onClick={() => navigate('/memory?q=&meeting_only=&listSort=created_at_asc&limit=10&offset=0')}>Explicit clear</button>
        <button onClick={() => navigate(-1)}>Previous view</button></>;
    }
    renderWithProviders(<><MemoryPage /><NavigateViews /></>, { initialEntries: ['/memory?q=initial&limit=10&offset=10'] });
    await act(async () => {});
    fireEvent.change(screen.getByRole('textbox', { name: 'Search memories' }), { target: { value: 'unapplied old draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'External view' }));
    await act(async () => {});
    expect(screen.getByRole('textbox', { name: 'Search memories' })).toHaveValue('external');
    expect(api.memory.search).toHaveBeenLastCalledWith('external', expect.objectContaining({ meeting_only: true, limit: 25, offset: 50 }));
    fireEvent.click(screen.getByRole('button', { name: 'Explicit clear' }));
    await act(async () => {});
    expect(api.memory.list).toHaveBeenLastCalledWith(expect.objectContaining({ meeting_only: false, sort: 'created_at_asc', limit: 10, offset: 0 }));
    expect(screen.getByRole('textbox', { name: 'Search memories' })).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: 'Previous view' }));
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(screen.getByRole('textbox', { name: 'Search memories' })).toHaveValue('external');
    expect(api.memory.search).toHaveBeenLastCalledWith('external', expect.objectContaining({ meeting_only: true, limit: 25, offset: 50 }));
    expect(vi.mocked(api.memory.search).mock.calls.some(([q]) => q === 'unapplied old draft')).toBe(false);
  });

  it('restores the active semantic search and boolean filters before the first request while preserving the independent list sort', async () => {
    document.cookie = mergeViewCookie('', 'memory', { ...defaultView('memory'), q: 'release', repo: 'repo', tags: 'decision, release', meeting_only: true, listSort: 'updated_at_asc', searchSort: 'created_at_asc', limit: 25, offset: 50 });
    renderWithProviders(<MemoryPage />, { initialEntries: ['/memory'] });
    await waitFor(() => expect(api.memory.search).toHaveBeenCalledTimes(1));
    expect(api.memory.list).not.toHaveBeenCalled();
    expect(api.memory.search).toHaveBeenCalledWith('release', { repo: 'repo', tags: ['decision', 'release'], meeting_only: true, sort: 'created_at_asc', limit: 25, offset: 50 });
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() => expect(api.memory.list).toHaveBeenCalledTimes(1));
    expect(api.memory.list).toHaveBeenLastCalledWith({ repo: 'repo', tags: ['decision', 'release'], meeting_only: true, sort: 'updated_at_asc', limit: 25, offset: 0 });
    expect(readViewCookie(document.cookie)[0].values).toMatchObject({ listSort: 'updated_at_asc', searchSort: 'created_at_asc' });
  });

  it('keeps unapplied query text local and restores only the committed search after leaving before the debounce', async () => {
    vi.useFakeTimers();
    document.cookie = mergeViewCookie('', 'memory', { ...defaultView('memory'), q: 'previous' });
    const first = renderWithProviders(<MemoryPage />, { initialEntries: ['/memory'] });
    await act(async () => {});
    fireEvent.change(screen.getByRole('textbox', { name: 'Search memories' }), { target: { value: 'unapplied draft' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Meetings only' }));
    await act(async () => {});
    expect(screen.getByRole('textbox', { name: 'Search memories' })).toHaveValue('unapplied draft');
    expect(readViewCookie(document.cookie)[0].values).toMatchObject({ q: 'previous', meeting_only: true });
    expect(api.memory.search).toHaveBeenLastCalledWith('previous', expect.objectContaining({ meeting_only: true }));
    first.unmount();
    vi.mocked(api.memory.search).mockClear();
    renderWithProviders(<MemoryPage />, { initialEntries: ['/memory'] });
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(screen.getByRole('textbox', { name: 'Search memories' })).toHaveValue('previous');
    expect(api.memory.search).toHaveBeenCalledTimes(1);
    expect(api.memory.search).toHaveBeenCalledWith('previous', expect.objectContaining({ meeting_only: true }));
  });

  it('persists the applied debounced search without changing the visible raw draft', async () => {
    vi.useFakeTimers();
    renderWithProviders(<MemoryPage />, { initialEntries: ['/memory'] });
    await act(async () => {});
    fireEvent.change(screen.getByRole('textbox', { name: 'Search memories' }), { target: { value: '  applied query  ' } });
    await act(async () => { vi.advanceTimersByTime(299); });
    expect(readViewCookie(document.cookie)).toEqual([]);
    expect(api.memory.search).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(api.memory.search).toHaveBeenCalledTimes(1);
    expect(api.memory.search).toHaveBeenCalledWith('applied query', expect.objectContaining({ sort: 'relevance', offset: 0 }));
    expect(readViewCookie(document.cookie)[0].values.q).toBe('applied query');
    expect(screen.getByRole('textbox', { name: 'Search memories' })).toHaveValue('  applied query  ');
  });
});
