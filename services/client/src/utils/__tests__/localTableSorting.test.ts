import { describe, expect, it } from 'vitest';
import { sortCompleteRows } from '../localTableSorting';

interface Row {
  id: number;
  value: string | number | boolean | null | undefined;
}
const columns = {
  value: {
    ascending: 'asc',
    descending: 'desc',
    select: (row: Row) => row.value,
  },
} as const;
const sorted = (rows: readonly Row[], sort: '' | 'asc' | 'desc') =>
  sortCompleteRows(rows, sort, columns, (row) => row.id).map((row) => row.id);

describe('immutable complete-array sorting', () => {
  it('preserves source order until activated and returns a new array', () => {
    const rows = Object.freeze([
      Object.freeze({ id: 2, value: 'Zulu' }),
      Object.freeze({ id: 1, value: 'alpha' }),
    ]);
    const result = sortCompleteRows(rows, '', columns, (row) => row.id);
    expect(result).toEqual(rows);
    expect(result).not.toBe(rows);
    expect(sorted(rows, 'asc')).toEqual([1, 2]);
    expect(rows.map((row) => row.id)).toEqual([2, 1]);
    expect(rows.map((row) => row.value)).toEqual(['Zulu', 'alpha']);
  });

  it.each(['asc', 'desc'] as const)(
    'keeps null and missing values last in %s order with stable ID ties',
    (sort) => {
      const rows = Object.freeze([
        { id: 4, value: null },
        { id: 3, value: 'beta' },
        { id: 2, value: undefined },
        { id: 1, value: 'alpha' },
      ]);
      expect(sorted(rows, sort)).toEqual(
        sort === 'asc' ? [1, 3, 2, 4] : [3, 1, 2, 4],
      );
    },
  );

  it('compares text case-insensitively with accents retained and IDs ascending in both directions', () => {
    const rows = [
      { id: 3, value: 'éclair' },
      { id: 2, value: 'ÉCLAIR' },
      { id: 1, value: 'Zulu' },
    ];
    expect(sorted(rows, 'asc')).toEqual([2, 3, 1]);
    expect(sorted(rows, 'desc')).toEqual([1, 2, 3]);
  });

  it('sorts raw numbers rather than lexical representations', () => {
    const rows = [
      { id: 1, value: 10 },
      { id: 2, value: -2 },
      { id: 3, value: 2.5 },
    ];
    expect(sorted(rows, 'asc')).toEqual([2, 3, 1]);
    expect(sorted(rows, 'desc')).toEqual([1, 3, 2]);
  });

  it('treats false as a real boolean value', () => {
    const rows = [
      { id: 3, value: null },
      { id: 2, value: true },
      { id: 1, value: false },
    ];
    expect(sorted(rows, 'asc')).toEqual([1, 2, 3]);
    expect(sorted(rows, 'desc')).toEqual([2, 1, 3]);
  });

  it('preserves source-index ties when the collection has no IDs', () => {
    const rows = [
      { id: 3, value: 'same' },
      { id: 2, value: 'SAME' },
      { id: 1, value: 'Same' },
    ];
    expect(sortCompleteRows(rows, 'desc', columns)).toEqual(rows);
  });

  it('rejects undeclared keys and invalid scalar numbers instead of guessing', () => {
    expect(() =>
      sortCompleteRows([{ id: 1, value: 1 }], 'unknown' as 'asc', columns),
    ).toThrow(/sort/i);
    for (const value of [NaN, Infinity, -Infinity])
      expect(() =>
        sortCompleteRows([{ id: 1, value }], 'asc', columns),
      ).toThrow(/finite/i);
  });
});
