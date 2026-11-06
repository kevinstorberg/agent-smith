import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { usePagination } from '../usePagination';

function deferred() {
  let resolve!: (value: { items: string[]; total: number }) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<{ items: string[]; total: number }>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

it.each([{ items: [] }, { items: ['accepted'] }])(
  'distinguishes the first read from later criteria refreshes after accepting %j',
  async ({ items }) => {
    const first = deferred();
    const next = deferred();
    const fetcher = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(next.promise);
    const { result, rerender } = renderHook(
      ({ sort }) => usePagination(fetcher, [sort]),
      { initialProps: { sort: 'ascending' } },
    );
    expect(result.current.initialLoading).toBe(true);
    await act(async () => first.resolve({ items, total: items.length }));
    expect(result.current.initialLoading).toBe(false);
    rerender({ sort: 'descending' });
    expect(result.current.loading).toBe(true);
    expect(result.current.initialLoading).toBe(false);
    expect(result.current.dataCurrent).toBe(false);
    expect(result.current.items).toEqual(items);
    await act(async () => next.resolve({ items: ['next'], total: 1 }));
    expect(result.current.initialLoading).toBe(false);
    expect(result.current.dataCurrent).toBe(true);
  },
);

describe('failure and retry presentation', () => {
  it.each([false, true])(
    'keeps accepted=%s across an error and pending retry',
    async (accepted) => {
      const retry = deferred();
      const fetcher = vi.fn();
      if (accepted)
        fetcher.mockResolvedValueOnce({ items: ['accepted'], total: 1 });
      fetcher
        .mockRejectedValueOnce(new Error('Unavailable'))
        .mockReturnValueOnce(retry.promise);
      const { result } = renderHook(() => usePagination(fetcher));
      if (accepted) {
        await waitFor(() => expect(result.current.dataCurrent).toBe(true));
        await act(async () => result.current.refresh());
      }
      await waitFor(() => expect(result.current.error).toBe('Unavailable'));
      expect(result.current.initialLoading).toBe(false);
      let pending!: Promise<void>;
      act(() => {
        pending = result.current.refresh();
      });
      expect(result.current.initialLoading).toBe(!accepted);
      await act(async () => {
        retry.resolve({ items: [], total: 0 });
        await pending;
      });
      expect(result.current.initialLoading).toBe(false);
      expect(result.current.error).toBeNull();
    },
  );

  it('never treats a rejected stale response as an accepted first result', async () => {
    const first = deferred();
    const current = deferred();
    const fetcher = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(current.promise);
    const { result, rerender } = renderHook(
      ({ sort }) => usePagination(fetcher, [sort]),
      { initialProps: { sort: 'old' } },
    );
    rerender({ sort: 'current' });
    await act(async () => first.resolve({ items: ['stale'], total: 1 }));
    expect(result.current.initialLoading).toBe(true);
    expect(result.current.items).toEqual([]);
    await act(async () => current.resolve({ items: [], total: 0 }));
    expect(result.current.initialLoading).toBe(false);
    expect(result.current.dataCurrent).toBe(true);
  });
});
