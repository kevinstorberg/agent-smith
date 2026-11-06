import type { EvalScenario } from '../../api';

const prefix = 'Shared complete prompt context '.repeat(8);
export const scenarioSortingRows: EvalScenario[] = [
  { id: 30, name: 'Zulu', prompt: `${prefix}Z`, enabled: false },
  { id: 20, name: 'alpha', prompt: `${prefix}B`, enabled: true },
  { id: 10, name: 'ALPHA', prompt: `${prefix}A`, enabled: true },
].map((row) => ({
  ...row,
  suite_id: 1,
  sort_key: row.id,
  created_at: '2026-11-01T12:00:00Z',
  updated_at: '2026-11-01T12:00:00Z',
}));
