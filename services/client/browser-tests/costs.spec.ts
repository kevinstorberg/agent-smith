import { test, expect } from './fixtures';
import { expectDocumentContained, expectMainContained } from './geometry';
import type { CostReport, CostResponse } from '../src/types/costs';

test.use({ timezoneId: 'America/New_York' });

const report: CostReport = {
  provider: 'aws',
  period_start: '2026-11-01',
  period_end: '2026-11-06',
  currency: 'USD',
  total: '12.25',
  estimated: true,
  scope: 'AWS billing visible to account 123456789012',
  fetched_at: '2026-11-05T15:00:00Z',
  data_through: '2026-11-04',
  cost_basis: 'UnblendedCost',
  daily: [{ label: '2026-11-04', amount: '12.25' }],
  breakdown: [
    { label: 'Amazon Bedrock', amount: '15.25' },
    { label: 'Credits', amount: '-3.00' },
  ],
  usage: [],
  notes: ['Not a final invoice.'],
};

test('AWS costs show provisional account totals, refunds and local update times at 200% text', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/costs/aws', {
    state: 'ready',
    report,
    error: null,
    next_refresh_at: '2026-11-06T15:00:00Z',
  });
  await page.goto('/costs');
  await expect(
    page.getByRole('heading', { name: 'Estimated charges' }),
  ).toBeVisible();
  const summary = page.getByRole('region', { name: 'Cost summary' });
  await expect(summary.getByText('$12.25', { exact: true })).toBeVisible();
  await expect(summary.getByText(report.scope, { exact: true })).toBeVisible();
  await expect(
    summary.getByText('2026-11-01 through 2026-11-06 (end exclusive, UTC)'),
  ).toBeVisible();
  await expect(summary.getByText(/Last updated:.*10:00:00 AM/)).toBeVisible();
  await expect(
    page.getByRole('region', { name: 'Costs by service' }).getByText('-$3.00'),
  ).toBeVisible();
  await expect(page.getByText('Not a final invoice.')).toBeVisible();
  await page.addStyleTag({ content: 'html { font-size: 200% !important; }' });
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('AWS pending report becomes ready through cached GET polling every 15 seconds', async ({
  page,
  fixtureAPI,
}) => {
  await page.clock.install({ time: new Date('2026-11-05T12:00:00Z') });
  await page.clock.pauseAt(new Date('2026-11-05T12:00:01Z'));
  let reads = 0;
  fixtureAPI.get('/api/costs/aws', () => {
    reads += 1;
    return reads === 1
      ? { state: 'pending', report: null, error: null }
      : { state: 'ready', report, error: null };
  });
  await page.goto('/costs');
  await expect(page.getByRole('status')).toHaveText(
    'The first cost report is being collected.',
  );
  expect(reads).toBe(1);
  await page.clock.runFor(14_999);
  expect(reads).toBe(1);
  const completed = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/costs/aws',
  );
  await page.clock.runFor(1);
  await (await completed).finished();
  await expect(
    page.getByRole('heading', { name: 'Estimated charges' }),
  ).toBeVisible();
  expect(reads).toBe(2);
  const costCalls = fixtureAPI.requests.filter((request) =>
    new URL(request.url).pathname.startsWith('/api/costs/'),
  );
  expect(costCalls.map((request) => request.method)).toEqual(['GET', 'GET']);
});

for (const state of ['disabled', 'stale'] as const) {
  test(`AWS ${state} report does not imply zero spending`, async ({
    page,
    fixtureAPI,
  }) => {
    const response: CostResponse =
      state === 'disabled'
        ? {
            state,
            report: null,
            message: 'Enable AWS_COSTS_ENABLED to collect costs.',
          }
        : {
            state,
            report,
            error: {
              code: 'permission_denied',
              message: 'Grant ce:GetCostAndUsage.',
            },
          };
    fixtureAPI.get('/api/costs/aws', response);
    await page.goto('/costs');
    if (state === 'disabled') {
      await expect(
        page.getByText('Enable AWS_COSTS_ENABLED to collect costs.'),
      ).toBeVisible();
      await expect(
        page.getByRole('region', { name: 'Cost summary' }),
      ).toHaveCount(0);
    } else {
      await expect(page.getByRole('status')).toHaveText(
        'Showing the last successful report; the latest refresh failed.',
      );
      await expect(page.getByRole('alert')).toHaveText(
        'Grant ce:GetCostAndUsage.',
      );
      await expect(
        page
          .getByRole('region', { name: 'Cost summary' })
          .getByText('$12.25', { exact: true }),
      ).toBeVisible();
    }
    await expect(page.getByText('$0.00', { exact: true })).toHaveCount(0);
    await expectDocumentContained(page);
    await expectMainContained(page);
  });
}
