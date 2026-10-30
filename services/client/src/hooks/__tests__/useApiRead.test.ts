import { useCallback } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useApiRead } from '../useApiRead';

describe('useApiRead', () => {
  it('loads data and exposes a failed read until a retry succeeds', async () => {
    const read = vi.fn().mockRejectedValueOnce(new Error('Read failed')).mockResolvedValueOnce('saved result');
    const { result } = renderHook(() => useApiRead(read));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe('Read failed');

    await act(async () => { await result.current.refresh(); });
    expect(result.current.data).toBe('saved result');
    expect(result.current.error).toBeNull();
  });

  it('reloads when the resource changes and ignores the older resource response', async () => {
    let resolveOld: (value: string) => void = () => undefined;
    const read = vi.fn()
      .mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce('new resource');
    const { result, rerender } = renderHook(({ id }) => useApiRead(useCallback(() => read(id), [id])), { initialProps: { id: 'first' } });
    const staleRefresh = result.current.refresh;

    rerender({ id: 'second' });
    await waitFor(() => expect(result.current.data).toBe('new resource'));
    await act(async () => { resolveOld('old resource'); });
    await act(async () => { await staleRefresh(); });
    expect(result.current.data).toBe('new resource');
    expect(read).toHaveBeenLastCalledWith('second');
    expect(read).toHaveBeenCalledTimes(2);
  });

  it('ignores an older request failure after a successful refresh', async () => {
    let rejectOld: (error: Error) => void = () => undefined;
    const read = vi.fn()
      .mockReturnValueOnce(new Promise((_, reject) => { rejectOld = reject; }))
      .mockResolvedValueOnce('current result');
    const { result } = renderHook(() => useApiRead(read));

    await act(async () => { await result.current.refresh(); });
    await act(async () => { rejectOld(new Error('Stale failure')); });
    expect(result.current.error).toBeNull();
    expect(result.current.data).toBe('current result');
  });

  it('keeps existing data visible during a background refresh', async () => {
    let resolveRefresh: (value: string) => void = () => undefined;
    const read = vi.fn().mockResolvedValueOnce('initial')
      .mockReturnValueOnce(new Promise(resolve => { resolveRefresh = resolve; }));
    const { result } = renderHook(() => useApiRead(read));
    await waitFor(() => expect(result.current.data).toBe('initial'));

    let refresh: Promise<void>;
    act(() => { refresh = result.current.refresh({ showLoading: false }); });
    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBe('initial');
    await act(async () => { resolveRefresh('updated'); await refresh!; });
    expect(result.current.data).toBe('updated');
  });

  it('does not commit a response after unmount', async () => {
    let resolveRead: (value: string) => void = () => undefined;
    const read = vi.fn().mockReturnValueOnce(new Promise(resolve => { resolveRead = resolve; }));
    const { result, unmount } = renderHook(() => useApiRead(read));
    unmount();

    await act(async () => { resolveRead('late result'); });
    await act(async () => { await result.current.refresh(); });
    expect(result.current.data).toBeNull();
    expect(read).toHaveBeenCalledTimes(1);
  });

  it('does not read while disabled and retains accepted data when reactivated', async () => {
    const read = vi.fn().mockResolvedValueOnce('cached').mockResolvedValueOnce('fresh');
    const { result, rerender } = renderHook(({ enabled }) => useApiRead(read, { enabled }), { initialProps: { enabled: false } });
    expect(result.current.loading).toBe(false);
    await act(async () => { await result.current.refresh(); });
    expect(read).not.toHaveBeenCalled();
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.data).toBe('cached'));
    const oldRefresh = result.current.refresh;
    rerender({ enabled: false });
    expect(result.current.data).toBe('cached');
    await act(async () => { await oldRefresh(); await result.current.refresh(); });
    expect(read).toHaveBeenCalledTimes(1);
    rerender({ enabled: true });
    expect(result.current.data).toBe('cached');
    await waitFor(() => expect(result.current.data).toBe('fresh'));
  });

  it('invalidates a pending response on deactivation and starts a fresh read on activation', async () => {
    let resolve!: (value: string) => void;
    const read = vi.fn().mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValueOnce('active result');
    const { result, rerender } = renderHook(({ enabled }) => useApiRead(read, { enabled }), { initialProps: { enabled: true } });
    rerender({ enabled: false });
    await act(async () => { resolve('hidden result'); });
    expect(result.current.data).toBeNull();
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.data).toBe('active result'));
    expect(read).toHaveBeenCalledTimes(2);
  });
});
