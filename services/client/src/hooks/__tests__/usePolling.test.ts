import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { POLL_INTERVAL_MS } from '../../constants';
import { usePolling } from '../usePolling';

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('usePolling', () => {
  it('defaults to a 15-second interval', () => {
    expect(POLL_INTERVAL_MS).toBe(15_000);
  });

  it('does not call immediately and calls after the interval', () => {
    vi.useFakeTimers();
    const callback = vi.fn();

    renderHook(() => usePolling(callback));

    expect(callback).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(14_999);
    });

    expect(callback).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });

    expect(callback).toHaveBeenCalledTimes(1);
  });

  it('skips ticks while the previous callback is still running', async () => {
    vi.useFakeTimers();
    let resolveCallback: () => void = () => undefined;
    const callback = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveCallback = resolve;
        }),
    );

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
    const { rerender } = renderHook(
      ({ enabled }) => usePolling(callback, { enabled }),
      {
        initialProps: { enabled: true },
      },
    );

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

  it('pauses while hidden and waits a full interval after becoming visible', async () => {
    vi.useFakeTimers();
    let hidden = false;
    vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
    const callback = vi.fn();
    renderHook(() => usePolling(callback));
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    act(() => {
      hidden = true;
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(callback).not.toHaveBeenCalled();
    act(() => {
      hidden = false;
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(14_999);
    });
    expect(callback).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it('uses the latest callback without restarting the visible interval', async () => {
    vi.useFakeTimers();
    const before = vi.fn();
    const after = vi.fn();
    const { rerender } = renderHook(({ callback }) => usePolling(callback), {
      initialProps: { callback: before },
    });
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    rerender({ callback: after });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(before).not.toHaveBeenCalled();
    expect(after).toHaveBeenCalledTimes(1);
  });

  it('contains callback errors and keeps polling', async () => {
    vi.useFakeTimers();
    const callback = vi
      .fn()
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

    expect(() =>
      renderHook(() => usePolling(callback, { intervalMs: 0 })),
    ).toThrow(/positive finite/);
  });
});
