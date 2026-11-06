import type { EvalRun } from '../../api';

export const resultSortingRows: EvalRun[] = Array.from(
  { length: 30 },
  (_, index) => ({
    id: index + 1,
    timestamp: `2026-01-${String(index + 1).padStart(2, '0')}T12:00:00Z`,
    eval_type: 'rules',
    subcategory: 'core',
    scenario: `Scenario ${String(index + 1).padStart(2, '0')}`,
    test_model: 'offline model',
    judge_model: 'offline judge',
    threshold: 0.8,
    score_avg: index / 30,
    score_count: 2,
    eval_suite_id: null,
    created_at: '2026-01-01T12:00:00Z',
  }),
);
