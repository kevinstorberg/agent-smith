import { act, renderHook } from '@testing-library/react';
import { expect, it } from 'vitest';
import { useLocalTableSort } from '../useLocalTableSort';

interface Row {
  id: number;
  name: string;
}
const columns = {
  name: {
    ascending: 'name_asc',
    descending: 'name_desc',
    select: (row: Row) => row.name,
  },
} as const;
const initial = [
  { id: 2, name: 'Zulu' },
  { id: 1, name: 'Alpha' },
];

it('keeps the selected display order across fresh arrays and can restore source order', () => {
  const { result, rerender } = renderHook(
    ({ rows }) => useLocalTableSort(rows, columns, (row) => row.id),
    { initialProps: { rows: initial } },
  );
  expect(result.current.sort).toBe('');
  expect(result.current.items.map((row) => row.id)).toEqual([2, 1]);
  act(() => result.current.setSort('name_asc'));
  const refreshed = [{ id: 3, name: 'Beta' }, ...initial];
  rerender({ rows: refreshed });
  expect(result.current.sort).toBe('name_asc');
  expect(result.current.items.map((row) => row.id)).toEqual([1, 3, 2]);
  expect(refreshed.map((row) => row.id)).toEqual([3, 2, 1]);
  act(() => result.current.setSort(''));
  expect(result.current.items.map((row) => row.id)).toEqual([3, 2, 1]);
});

it('starts from source order after remount rather than saving another preference', () => {
  const first = renderHook(() =>
    useLocalTableSort(initial, columns, (row) => row.id),
  );
  act(() => first.result.current.setSort('name_desc'));
  first.unmount();
  const second = renderHook(() =>
    useLocalTableSort(initial, columns, (row) => row.id),
  );
  expect(second.result.current.sort).toBe('');
  expect(second.result.current.items.map((row) => row.id)).toEqual([2, 1]);
});
