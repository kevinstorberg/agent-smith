import { useMemo, useState } from 'react';
import { sortCompleteRows } from '../utils/localTableSorting';
import type {
  LocalSortColumn,
  LocalSortToken,
} from '../utils/localTableSorting';

export function useLocalTableSort<
  Row,
  const C extends Readonly<Record<string, LocalSortColumn<Row, string>>>,
>(rows: readonly Row[], columns: C, getId?: (row: Row) => string | number) {
  const [sort, setSort] = useState<LocalSortToken<C> | ''>('');
  const items = useMemo(
    () => sortCompleteRows(rows, sort, columns, getId),
    [rows, sort, columns, getId],
  );
  return { items, sort, setSort };
}
