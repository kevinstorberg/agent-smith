import { columnSortOptions } from './tableSorting';
export const EVIDENCE_SORT_COLUMNS = {
  observation: { ascending: 'observation_asc', descending: 'observation_desc' },
  type: { ascending: 'type_asc', descending: 'type_desc' },
  confidence: { ascending: 'confidence_asc', descending: 'confidence_desc' },
  review: { ascending: 'review_asc', descending: 'review_desc' },
  source: { ascending: 'source_asc', descending: 'source_desc' },
} as const;
const options = [
  { value: 'oldest' },
  { value: 'newest' },
  ...columnSortOptions(EVIDENCE_SORT_COLUMNS),
] as const;
export type EvidenceSort =
  | 'oldest'
  | 'newest'
  | (typeof EVIDENCE_SORT_COLUMNS)[keyof typeof EVIDENCE_SORT_COLUMNS][
      'ascending' | 'descending'];
export function parseEvidenceSort(value: string | null): EvidenceSort {
  return (
    (options.find((option) => option.value === value)?.value as
      EvidenceSort | undefined) ?? 'newest'
  );
}
