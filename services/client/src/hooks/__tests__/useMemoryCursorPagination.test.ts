import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MemoryCursorPage } from '../../api';
import { useMemoryCursorPagination } from '../useMemoryCursorPagination';

const page = (
  content: string,
  next: string | null = null,
): MemoryCursorPage => ({
  mode: 'cursor',
  items: [{ id: content, content }],
  next_cursor: next,
  order: 'id_asc',
});
const options = { enabled: true, limit: 10, source: 'test-index' };

afterEach(() => vi.useRealTimers());

describe('useMemoryCursorPagination', () => {
  it('makes one request per navigation and refresh, without idle traversal or polling', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce(page('first', 'second-token'))
      .mockResolvedValueOnce(page('second', 'third-token'))
      .mockResolvedValueOnce(page('first refreshed', 'second-token'))
      .mockResolvedValueOnce(page('first refreshed again', 'second-token'));
    const { result } = renderHook(() =>
      useMemoryCursorPagination(fetchPage, options),
    );
    await waitFor(() => expect(result.current.items[0]?.content).toBe('first'));
    expect(fetchPage).toHaveBeenCalledExactlyOnceWith(10, null);
    act(() => result.current.next());
    await waitFor(() => expect(result.current.page).toBe(2));
    expect(fetchPage).toHaveBeenLastCalledWith(10, 'second-token');
    act(() => result.current.previous());
    await waitFor(() =>
      expect(result.current.items[0]?.content).toBe('first refreshed'),
    );
    await act(async () => {
      await result.current.refresh();
    });
    expect(fetchPage).toHaveBeenCalledTimes(4);
    expect(fetchPage).toHaveBeenLastCalledWith(10, null);
    vi.useFakeTimers();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetchPage).toHaveBeenCalledTimes(4);
  });

  it('keeps successful history after failed navigation and retries only the failed page', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce(page('first', 'second-token'))
      .mockRejectedValueOnce(new Error('expired cursor'))
      .mockResolvedValueOnce(page('second'));
    const { result } = renderHook(() =>
      useMemoryCursorPagination(fetchPage, options),
    );
    await waitFor(() => expect(result.current.items[0]?.content).toBe('first'));
    act(() => result.current.next());
    await waitFor(() => expect(result.current.error).toBe('expired cursor'));
    expect(result.current.page).toBe(1);
    expect(result.current.hasPrevious).toBe(false);
    expect(result.current.items[0]?.content).toBe('first');
    await act(async () => {
      await result.current.retry();
    });
    expect(result.current.page).toBe(2);
    expect(result.current.hasPrevious).toBe(true);
    expect(fetchPage.mock.calls).toEqual([
      [10, null],
      [10, 'second-token'],
      [10, 'second-token'],
    ]);
  });

  it('refreshes the successful current page after a failed navigation', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce(page('first', 'second-token'))
      .mockRejectedValueOnce(new Error('unavailable'))
      .mockResolvedValueOnce(page('first refreshed'));
    const { result } = renderHook(() =>
      useMemoryCursorPagination(fetchPage, options),
    );
    await waitFor(() => expect(result.current.items[0]?.content).toBe('first'));
    act(() => result.current.next());
    await waitFor(() => expect(result.current.error).not.toBeNull());
    await act(async () => {
      await result.current.refresh();
    });
    await waitFor(() =>
      expect(result.current.items[0]?.content).toBe('first refreshed'),
    );
    expect(fetchPage).toHaveBeenCalledTimes(3);
    expect(fetchPage).toHaveBeenLastCalledWith(10, null);
  });

  it('resets size, source and reactivated browsing to the first page and ignores older responses', async () => {
    let resolveOld!: (value: MemoryCursorPage) => void;
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce(page('first', 'second-token'))
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
      )
      .mockResolvedValue(page('current', 'next-token'));
    const { result, rerender } = renderHook(
      (props) => useMemoryCursorPagination(fetchPage, props),
      { initialProps: options },
    );
    await waitFor(() => expect(result.current.items[0]?.content).toBe('first'));
    act(() => result.current.next());
    expect(result.current.loading).toBe(true);
    await act(async () => {
      result.current.next();
      result.current.previous();
      await result.current.refresh();
      await result.current.restart();
    });
    expect(fetchPage).toHaveBeenCalledTimes(2);
    rerender({ ...options, limit: 25 });
    await waitFor(() =>
      expect(result.current.items[0]?.content).toBe('current'),
    );
    await act(async () => {
      resolveOld(page('stale'));
    });
    expect(result.current.items[0]?.content).toBe('current');
    expect(result.current.page).toBe(1);
    expect(fetchPage).toHaveBeenLastCalledWith(25, null);
    rerender({ ...options, limit: 25, source: 'other-index' });
    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(4));
    rerender({ ...options, enabled: false });
    await act(async () => {
      await result.current.refresh();
    });
    expect(fetchPage).toHaveBeenCalledTimes(4);
    rerender(options);
    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(5));
    expect(fetchPage).toHaveBeenLastCalledWith(10, null);
  });

  it('does not revive an earlier native page while a new browsing session loads', async () => {
    let resolve!: (value: MemoryCursorPage) => void;
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce(page('first', 'second-token'))
      .mockResolvedValueOnce(page('old second'))
      .mockReturnValueOnce(
        new Promise((done) => {
          resolve = done;
        }),
      );
    const { result, rerender } = renderHook(
      (props) => useMemoryCursorPagination(fetchPage, props),
      { initialProps: options },
    );
    await waitFor(() => expect(result.current.items[0]?.content).toBe('first'));
    act(() => result.current.next());
    await waitFor(() => expect(result.current.page).toBe(2));
    rerender({ ...options, enabled: false });
    rerender(options);
    expect(result.current.items).toEqual([]);
    expect(result.current.page).toBe(1);
    expect(result.current.loading).toBe(true);
    expect(fetchPage).toHaveBeenLastCalledWith(10, null);
    await act(async () => {
      resolve(page('new first'));
    });
    expect(result.current.items[0]?.content).toBe('new first');
    expect(result.current.page).toBe(1);
    expect(fetchPage).toHaveBeenCalledTimes(3);
  });

  it('allows an empty page with a next cursor without automatically filling it', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValue({ ...page('', 'next-token'), items: [] });
    const { result } = renderHook(() =>
      useMemoryCursorPagination(fetchPage, options),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toEqual([]);
    expect(result.current.hasNext).toBe(true);
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });
});
