import { renderHook, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { usePagination } from '../usePagination';

describe('usePagination', () => {
  it('calls fetcher with default limit and offset', async () => {
    const fetcher = vi.fn().mockResolvedValue({ items: ['a', 'b'], total: 2 });
    const { result } = renderHook(() => usePagination(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetcher).toHaveBeenCalledWith(10, 0);
    expect(result.current.items).toEqual(['a', 'b']);
    expect(result.current.total).toBe(2);
  });

  it('sets loading true while fetching', () => {
    const fetcher = vi.fn().mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => usePagination(fetcher));
    expect(result.current.loading).toBe(true);
  });

  it('re-fetches when offset changes', async () => {
    const fetcher = vi.fn().mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => usePagination(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetcher).toHaveBeenCalledTimes(1);

    act(() => { result.current.setOffset(10); });
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(fetcher).toHaveBeenLastCalledWith(10, 10);
  });

  it('re-fetches when limit changes', async () => {
    const fetcher = vi.fn().mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => usePagination(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setLimit(25); });
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(fetcher).toHaveBeenLastCalledWith(25, 0);
  });

  it('allows setItems to update items directly', async () => {
    const fetcher = vi.fn().mockResolvedValue({ items: [1, 2, 3], total: 3 });
    const { result } = renderHook(() => usePagination(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setItems([3, 2, 1]); });
    expect(result.current.items).toEqual([3, 2, 1]);
  });

  it('refreshes the current page on demand', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ items: ['a'], total: 1 })
      .mockResolvedValueOnce({ items: ['b'], total: 1 });
    const { result } = renderHook(() => usePagination(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.refresh();
    });

    expect(fetcher).toHaveBeenLastCalledWith(10, 0);
    expect(result.current.items).toEqual(['b']);
  });

  it('can refresh without entering a loading state', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ items: ['a'], total: 1 })
      .mockResolvedValueOnce({ items: ['b'], total: 1 });
    const { result } = renderHook(() => usePagination(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));

    let refreshPromise: Promise<void>;
    act(() => {
      refreshPromise = result.current.refresh({ showLoading: false });
    });

    expect(result.current.loading).toBe(false);

    await act(async () => {
      await refreshPromise!;
    });

    expect(result.current.items).toEqual(['b']);
  });

  it('ignores stale responses when a newer refresh completes first', async () => {
    let resolveFirst: (value: { items: string[]; total: number }) => void = () => undefined;
    let resolveSecond: (value: { items: string[]; total: number }) => void = () => undefined;
    const fetcher = vi.fn()
      .mockReturnValueOnce(new Promise(resolve => { resolveFirst = resolve; }))
      .mockReturnValueOnce(new Promise(resolve => { resolveSecond = resolve; }));

    const { result } = renderHook(() => usePagination(fetcher));

    let refreshPromise: Promise<void>;
    act(() => {
      refreshPromise = result.current.refresh({ showLoading: false });
    });

    await act(async () => {
      resolveSecond({ items: ['new'], total: 1 });
      await refreshPromise!;
    });

    await act(async () => {
      resolveFirst({ items: ['old'], total: 1 });
      await Promise.resolve();
    });

    expect(result.current.items).toEqual(['new']);
  });

  it('does not commit a response after unmount', async () => {
    let resolveFetch: (value: { items: string[]; total: number }) => void = () => undefined;
    const fetcher = vi.fn().mockReturnValue(new Promise(resolve => { resolveFetch = resolve; }));
    const { result, unmount } = renderHook(() => usePagination(fetcher));

    expect(result.current.loading).toBe(true);
    unmount();

    await act(async () => {
      resolveFetch({ items: ['late'], total: 1 });
      await Promise.resolve();
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
