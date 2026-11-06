import type { SortColumn } from './tableSorting';

export type LocalSortValue = string | number | boolean | null | undefined;
export interface LocalSortColumn<Row, T extends string> extends SortColumn<T> {
  readonly select: (row: Row) => LocalSortValue;
}
export type LocalSortToken<
  C extends Readonly<Record<string, SortColumn<string>>>,
> = C[keyof C]['ascending' | 'descending'];

function compareValues(
  left: Exclude<LocalSortValue, null | undefined>,
  right: Exclude<LocalSortValue, null | undefined>,
): number {
  if (typeof left !== typeof right)
    throw new Error('A local sort column requires keys of the same type.');
  if (typeof left === 'string' && typeof right === 'string') {
    return left.localeCompare(right, 'en', { sensitivity: 'accent' });
  }
  return Number(left) - Number(right);
}

export function sortCompleteRows<
  Row,
  const C extends Readonly<Record<string, LocalSortColumn<Row, string>>>,
>(
  rows: readonly Row[],
  sort: LocalSortToken<C> | '',
  columns: C,
  getId?: (row: Row) => string | number,
): Row[] {
  if (sort === '') return [...rows];
  const column = Object.values(columns).find(
    (value) => value.ascending === sort || value.descending === sort,
  );
  if (!column) throw new Error(`Unknown local table sort: ${sort}`);
  const direction = sort === column.ascending ? 1 : -1;
  const selected = rows.map((row, index) => {
    const value = column.select(row);
    if (typeof value === 'number' && !Number.isFinite(value))
      throw new Error('Local numeric sort keys must be finite.');
    return { row, index, value, id: getId?.(row) };
  });
  selected.sort((left, right) => {
    const leftMissing = left.value == null;
    const rightMissing = right.value == null;
    if (leftMissing !== rightMissing) return leftMissing ? 1 : -1;
    const comparison =
      leftMissing || rightMissing
        ? 0
        : compareValues(left.value!, right.value!);
    if (comparison) return comparison * direction;
    if (left.id !== undefined && right.id !== undefined && left.id !== right.id)
      return left.id < right.id ? -1 : 1;
    return left.index - right.index;
  });
  return selected.map((value) => value.row);
}
