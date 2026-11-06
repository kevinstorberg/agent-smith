import { compareDecimalStrings, parseDecimal } from './decimalSorting';
import { compareLocalSortValues } from './localTableSorting';
interface CostRow {
  label: string;
  amount: string;
  unit?: string;
}
const label = {
  ascending: 'label_asc',
  descending: 'label_desc',
  select: (row: CostRow) => row.label || null,
} as const;
const amount = {
  ascending: 'amount_asc',
  descending: 'amount_desc',
  select: (row: CostRow) => (parseDecimal(row.amount) ? row.amount : null),
  compareRows: (left: CostRow, right: CostRow) =>
    compareDecimalStrings(left.amount, right.amount),
} as const;
export const COST_SORT_COLUMNS = { label, amount } as const;
export const USAGE_SORT_COLUMNS = {
  label,
  amount: {
    ...amount,
    compareRows: (left: CostRow, right: CostRow) =>
      compareLocalSortValues(left.unit ?? '', right.unit ?? '') ||
      compareDecimalStrings(left.amount, right.amount),
  },
} as const;
