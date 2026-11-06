export type SortDirection = 'ascending' | 'descending';

export interface SortColumn<T extends string> {
  readonly ascending: T;
  readonly descending: T;
  readonly defaultDirection?: SortDirection;
}

export function columnDirection<T extends string>(
  sort: string,
  column: SortColumn<T>,
): SortDirection | undefined {
  if (sort === column.ascending) return 'ascending';
  if (sort === column.descending) return 'descending';
  return undefined;
}

export function nextColumnSort<T extends string>(
  sort: string,
  column: SortColumn<T>,
): T {
  const selected = columnDirection(sort, column);
  const next =
    selected === 'ascending'
      ? 'descending'
      : selected === 'descending'
        ? 'ascending'
        : (column.defaultDirection ?? 'ascending');
  return column[next];
}

type ColumnTokens<C extends Readonly<Record<string, SortColumn<string>>>> =
  C[keyof C]['ascending' | 'descending'];

export function columnSortOptions<
  const C extends Readonly<Record<string, SortColumn<string>>>,
>(columns: C): { value: ColumnTokens<C>; label: string }[] {
  const tokens = Object.values(columns).flatMap((column) => [
    column.ascending,
    column.descending,
  ]) as ColumnTokens<C>[];
  return [...new Set(tokens)].map((value) => ({ value, label: value }));
}
