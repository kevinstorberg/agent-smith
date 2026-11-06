import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CostsPage } from '../CostsPage';
import { api } from '../../api';
import { costSortingReport as report } from './costSortingFixture';
import { sortCompleteRows } from '../../utils/localTableSorting';
import { COST_SORT_COLUMNS, USAGE_SORT_COLUMNS } from '../../utils/costSorting';
vi.mock('../../api', () => ({ api: { costs: { get: vi.fn() } } }));
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.costs.get).mockImplementation(async (provider) => ({
    state: 'ready',
    report: { ...report, provider },
  }));
});
afterEach(() => vi.useRealTimers());
const labels = (name: string) =>
  within(screen.getByRole('region', { name }))
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[0].textContent);
it('orders exact decimals with credits, sub-cent values and missing usage last without mutating reports', () => {
  const before = structuredClone(report);
  expect(
    sortCompleteRows(report.breakdown, 'amount_asc', COST_SORT_COLUMNS).map(
      (row) => row.label,
    ),
  ).toEqual(['Credit', 'Smaller', 'Small', 'Two', 'Ten']);
  expect(
    sortCompleteRows(report.usage, 'amount_desc', USAGE_SORT_COLUMNS).map(
      (row) => row.label,
    ),
  ).toEqual(['Write ten', 'Read ten', 'Read two', 'Unknown']);
  expect(report).toEqual(before);
});
it('sorts each complete report independently without refetching and resets on provider change', async () => {
  render(<CostsPage />);
  await screen.findByText('Ten');
  fireEvent.click(screen.getByRole('button', { name: 'Pinecone' }));
  await screen.findByText('Read two');
  const reads = vi.mocked(api.costs.get).mock.calls.length;
  const costs = screen.getByRole('region', {
    name: 'Costs by service',
  });
  fireEvent.click(within(costs).getByRole('button', { name: 'Cost' }));
  expect(labels('Costs by service table')).toEqual([
    'Credit',
    'Smaller',
    'Small',
    'Two',
    'Ten',
  ]);
  fireEvent.click(within(costs).getByRole('button', { name: 'Cost' }));
  expect(labels('Costs by service table')).toEqual([
    'Ten',
    'Two',
    'Small',
    'Smaller',
    'Credit',
  ]);
  const usage = screen.getByRole('region', {
    name: 'Observed usage',
  });
  fireEvent.click(
    within(usage).getByRole('button', { name: 'Observed amount' }),
  );
  expect(labels('Observed usage table')).toEqual([
    'Read two',
    'Read ten',
    'Write ten',
    'Unknown',
  ]);
  const daily = screen.getByRole('region', {
    name: 'Daily costs',
  });
  fireEvent.click(
    within(daily).getByRole('button', {
      name: 'Billing day (UTC)',
    }),
  );
  expect(labels('Daily costs table')).toEqual([
    '2026-11-01',
    '2026-11-02',
    '2026-11-03',
  ]);
  expect(labels('Costs by service table')[0]).toBe('Ten');
  expect(api.costs.get).toHaveBeenCalledTimes(reads);
  fireEvent.click(screen.getByRole('button', { name: 'AWS' }));
  await screen.findByText('Ten');
  expect(
    within(screen.getByRole('region', { name: 'Costs by service' })).getByRole(
      'columnheader',
      { name: 'Cost' },
    ),
  ).not.toHaveAttribute('aria-sort');
});
it('retains local sort while polling replaces the complete report', async () => {
  vi.useFakeTimers();
  render(<CostsPage />);
  await act(async () => {});
  const section = screen.getByRole('region', {
    name: 'Costs by service',
  });
  fireEvent.click(within(section).getByRole('button', { name: 'Cost' }));
  vi.mocked(api.costs.get).mockResolvedValue({
    state: 'ready',
    report: {
      ...report,
      provider: 'aws',
      breakdown: [
        ...report.breakdown,
        { label: 'Larger credit', amount: '-4' },
      ],
    },
  });
  await act(async () => vi.advanceTimersByTime(15000));
  expect(labels('Costs by service table')[0]).toBe('Larger credit');
  expect(api.costs.get).toHaveBeenCalledTimes(2);
});
