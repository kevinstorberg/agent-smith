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
});
