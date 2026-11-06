import { describe, expect, expectTypeOf, it } from 'vitest';
import {
  columnDirection,
  columnSortOptions,
  nextColumnSort,
} from '../tableSorting';

const columns = {
  name: { ascending: 'name', descending: 'name_desc' },
  updated: {
    ascending: 'updated_asc',
    descending: 'updated',
    defaultDirection: 'descending',
  },
} as const;

describe('table column sort contracts', () => {
  it('recognizes only the selected column pair', () => {
    expect(columnDirection('name', columns.name)).toBe('ascending');
    expect(columnDirection('name_desc', columns.name)).toBe('descending');
    expect(columnDirection('manual', columns.name)).toBeUndefined();
  });

  it('starts ascending and reverses the requested sort', () => {
    expect(nextColumnSort('manual', columns.name)).toBe('name');
    expect(nextColumnSort('name', columns.name)).toBe('name_desc');
    expect(nextColumnSort('name_desc', columns.name)).toBe('name');
  });

  it('honors descending defaults only when entering another column', () => {
    expect(nextColumnSort('name', columns.updated)).toBe('updated');
    expect(nextColumnSort('updated', columns.updated)).toBe('updated_asc');
    expect(nextColumnSort('updated_asc', columns.updated)).toBe('updated');
  });

  it('derives exact literal options, deduplicates aliases and leaves definitions untouched', () => {
    const definitions = Object.freeze({ ...columns, repeated: columns.name });
    const options = columnSortOptions(definitions);
    expect(options).toEqual([
      { value: 'name', label: 'name' },
      { value: 'name_desc', label: 'name_desc' },
      { value: 'updated_asc', label: 'updated_asc' },
      { value: 'updated', label: 'updated' },
    ]);
    expectTypeOf(options[0].value).toEqualTypeOf<
      'name' | 'name_desc' | 'updated_asc' | 'updated'
    >();
    expect(definitions.repeated).toBe(columns.name);
    expect(columnSortOptions({})).toEqual([]);
  });
});
