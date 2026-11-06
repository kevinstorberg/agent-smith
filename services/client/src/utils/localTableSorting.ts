import type { SortColumn } from './tableSorting';

export type LocalSortValue = string | number | boolean | null | undefined;
export interface LocalSortColumn<Row, T extends string> extends SortColumn<T> {
  readonly select: (row: Row) => LocalSortValue;
  readonly compareRows?: (left: Row, right: Row) => number;
}
export type LocalSortToken<
  C extends Readonly<Record<string, SortColumn<string>>>,
> = C[keyof C]['ascending' | 'descending'];

export function compareLocalSortValues(
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
    const id = getId?.(row);
    if (typeof value === 'number' && !Number.isFinite(value))
      throw new Error('Local numeric sort keys must be finite.');
    if (typeof id === 'number' && !Number.isFinite(id))
      throw new Error('Local numeric IDs must be finite.');
    return { row, index, value, id };
  });
  selected.sort((left, right) => {
    const leftMissing = left.value == null;
    const rightMissing = right.value == null;
    if (leftMissing !== rightMissing) return leftMissing ? 1 : -1;
    const comparison =
      leftMissing || rightMissing
        ? 0
        : column.compareRows
          ? column.compareRows(left.row, right.row)
          : compareLocalSortValues(left.value!, right.value!);
    if (comparison) return comparison * direction;
    if (
      left.id !== undefined &&
      right.id !== undefined &&
      left.id !== right.id
    ) {
      if (typeof left.id !== typeof right.id)
        return typeof left.id === 'number' ? -1 : 1;
      return left.id < right.id ? -1 : 1;
    }
    return left.index - right.index;
  });
  return selected.map((value) => value.row);
}
