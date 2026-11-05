import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CostsPage } from '../CostsPage';
import { api } from '../../api';

vi.mock('../../api', () => ({ api: { costs: { get: vi.fn() } } }));

const report = {
  provider: 'aws',
  period_start: '2026-11-01',
  period_end: '2026-11-06',
  currency: 'USD',
  total: '12.25',
  estimated: true,
  scope: 'AWS billing visible to account 123456789012',
  fetched_at: '2026-11-05T15:00:00Z',
  cost_basis: 'UnblendedCost',
  data_through: '2026-11-04',
  daily: [{ label: '2026-11-04', amount: '12.25' }],
  breakdown: [
    { label: 'Amazon Bedrock', amount: '15.25' },
    { label: 'Credits', amount: '-3' },
  ],
  usage: [],
  notes: ['Not a final invoice.'],
};

beforeEach(() => {
  vi.resetAllMocks();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('CostsPage', () => {
  it('shows current-month scope, provisional spending, daily costs and credits', async () => {
    vi.mocked(api.costs.get).mockResolvedValue({
      state: 'ready',
      report,
      next_refresh_at: '2026-11-06T15:00:00Z',
      error: null,
    });
    render(<CostsPage />);
    expect(
      await screen.findByText('$12.25', { selector: 'strong' }),
    ).toBeVisible();
    expect(screen.getByText('This month')).toBeVisible();
    expect(screen.getByText(report.scope)).toBeVisible();
    expect(screen.getByText('Estimated charges')).toBeVisible();
    expect(screen.getByText('Amazon Bedrock')).toBeVisible();
    expect(screen.getByText('-$3.00')).toBeVisible();
    expect(screen.getByText(/Billing dates use UTC/)).toBeVisible();
  });

  it('shows unavailable costs instead of a zero when disabled or permissions fail', async () => {
    vi.mocked(api.costs.get).mockResolvedValue({
      state: 'failed',
      report: null,
      error: {
        code: 'permission_denied',
        message: 'Grant ce:GetCostAndUsage.',
      },
    });
    render(<CostsPage />);
    expect(await screen.findByText('Grant ce:GetCostAndUsage.')).toBeVisible();
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument();
  });

  it('retains visibly stale costs after a failed provider refresh', async () => {
    vi.mocked(api.costs.get).mockResolvedValue({
      state: 'stale',
      report,
      error: { code: 'provider_error', message: 'AWS is unavailable.' },
    });
    render(<CostsPage />);
    expect(
      await screen.findByText(/Showing the last successful report/),
    ).toBeVisible();
    expect(screen.getByText('$12.25', { selector: 'strong' })).toBeVisible();
    expect(screen.getByText('AWS is unavailable.')).toBeVisible();
  });

  it('refreshes the cached endpoint every15 seconds and stops when unmounted', async () => {
    vi.useFakeTimers();
    vi.mocked(api.costs.get).mockResolvedValue({
      state: 'ready',
      report,
      error: null,
    });
    const view = render(<CostsPage />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(api.costs.get).toHaveBeenCalledTimes(1);
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(api.costs.get).toHaveBeenCalledTimes(2);
    view.unmount();
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(api.costs.get).toHaveBeenCalledTimes(2);
  });
});
