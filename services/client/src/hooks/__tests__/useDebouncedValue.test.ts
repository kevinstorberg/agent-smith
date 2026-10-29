import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useDebouncedValue } from '../useDebouncedValue';

afterEach(() => vi.useRealTimers());

it('commits only the latest typed value after the shared delay and cancels on unmount', () => {
  vi.useFakeTimers();
  const { result, rerender, unmount } = renderHook(({ value }) => useDebouncedValue(value), { initialProps: { value: '' } });
  rerender({ value: 'pro' });
  act(() => vi.advanceTimersByTime(200));
  rerender({ value: 'product' });
  act(() => vi.advanceTimersByTime(299));
  expect(result.current).toBe('');
  act(() => vi.advanceTimersByTime(1));
  expect(result.current).toBe('product');
  rerender({ value: 'security' });
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
