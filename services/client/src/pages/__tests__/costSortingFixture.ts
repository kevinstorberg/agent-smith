import type { CostReport } from '../../types/costs';
export const costSortingReport: CostReport = {
  provider: 'pinecone',
  period_start: '2026-11-01',
  period_end: '2026-11-06',
  currency: 'USD',
  total: '12.25',
  estimated: true,
  scope: 'Fixture project',
  fetched_at: '2026-11-05T15:00:00Z',
  cost_basis: 'observed usage',
  notes: [],
  breakdown: [
    { label: 'Ten', amount: '10' },
    { label: 'Two', amount: '2' },
    { label: 'Credit', amount: '-3' },
    { label: 'Small', amount: '0.000001' },
    { label: 'Smaller', amount: '0.0000009' },
  ],
  daily: [
    { label: '2026-11-03', amount: '10' },
    { label: '2026-11-01', amount: '2' },
    { label: '2026-11-02', amount: '-3' },
  ],
  usage: [
    { label: 'Write ten', amount: '10', unit: 'write units' },
    { label: 'Read ten', amount: '10', unit: 'read units' },
    { label: 'Read two', amount: '2', unit: 'read units' },
    { label: 'Unknown', amount: 'Unavailable', unit: 'read units' },
  ],
};
