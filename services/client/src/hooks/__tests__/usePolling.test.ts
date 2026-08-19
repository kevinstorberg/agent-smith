import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { POLL_INTERVAL_MS } from '../../constants';
import { usePolling } from '../usePolling';

afterEach(() => {
  vi.useRealTimers();
});

describe('usePolling', () => {
  it('defaults to a 60-second interval', () => {
    expect(POLL_INTERVAL_MS).toBe(60_000);
  });

  it('does not call immediately and calls after the interval', () => {
    vi.useFakeTimers();
    const callback = vi.fn();

    renderHook(() => usePolling(callback));

    expect(callback).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });

    expect(callback).toHaveBeenCalledTimes(1);
  });

  it('skips ticks while the previous callback is still running', async () => {
    vi.useFakeTimers();
    let resolveCallback: () => void = () => undefined;
    const callback = vi.fn(() => new Promise<void>(resolve => {
      resolveCallback = resolve;
    }));

    renderHook(() => usePolling(callback));

    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });

    expect(callback).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveCallback();
      await Promise.resolve();
    });

    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });

    expect(callback).toHaveBeenCalledTimes(2);
  });

  it('stops polling when disabled', () => {
    vi.useFakeTimers();
    const callback = vi.fn();
    const { rerender } = renderHook(({ enabled }) => usePolling(callback, { enabled }), {
      initialProps: { enabled: true },
    });

    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });

    rerender({ enabled: false });

    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 2);
    });

    expect(callback).toHaveBeenCalledTimes(1);
  });

  it('clears the interval on unmount', () => {
    vi.useFakeTimers();
    const callback = vi.fn();
    const { unmount } = renderHook(() => usePolling(callback));

    unmount();

    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });

    expect(callback).not.toHaveBeenCalled();
  });

  it('contains callback errors and keeps polling', async () => {
    vi.useFakeTimers();
    const callback = vi.fn()
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValue(undefined);

    renderHook(() => usePolling(callback));

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
      await Promise.resolve();
    });

    act(() => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });

    expect(callback).toHaveBeenCalledTimes(2);
  });

  it('rejects invalid intervals', () => {
    const callback = vi.fn();

    expect(() => renderHook(() => usePolling(callback, { intervalMs: 0 })))
      .toThrow(/positive finite/);
  });
});
