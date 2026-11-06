import type { EvalSuite } from '../../api';

export const suiteSortingRows: EvalSuite[] = Array.from(
  { length: 30 },
  (_, index) => ({
    id: index + 1,
    name: `Suite ${String(index + 1).padStart(2, '0')}`,
    eval_type: 'rules',
    subcategory: 'core',
    judge_prompt: 'Complete judge prompt',
    items: {},
    config: {},
    enabled: index % 2 === 0,
    scenario_count: index,
    created_at: '2026-01-01T12:00:00Z',
    updated_at: '2026-01-01T12:00:00Z',
  }),
);
