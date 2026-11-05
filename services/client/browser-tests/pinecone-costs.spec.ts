import { readFileSync } from 'node:fs';
import { test, expect, type APIRequest } from './fixtures';
import type { CostReport } from '../src/types/costs';
import {
  expectDocumentContained,
  expectMainContained,
  expectControlsUnclipped,
} from './geometry';

const fixture = JSON.parse(
  readFileSync(
    new URL(
      '../src/pages/__tests__/pineconeCostsFixture.json',
      import.meta.url,
    ),
    'utf8',
  ),
) as {
  baseline: CostReport;
  observed: CostReport;
  no_price: CostReport;
  utc_boundary: CostReport;
};
const aws = {
  ...fixture.observed,
  provider: 'aws',
  scope: 'Synthetic AWS billing account',
  total: '12.25',
  cost_basis: 'UnblendedCost',
  usage: [],
  notes: [],
};
const ready = (report: CostReport) => ({ state: 'ready', report, error: null });
test.use({ timezoneId: 'America/New_York', locale: 'en-US' });

test('Pinecone shows native baseline quantities with unavailable history and local update time', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/costs/aws', ready(aws));
  fixtureAPI.get('/api/costs/pinecone', ready(fixture.utc_boundary));
  await page.goto('/costs');
  await page.getByRole('button', { name: 'Pinecone', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Observed usage estimate', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Cost unavailable for this period', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('History before the monitoring baseline is unavailable.', {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText('4096 bytes', { exact: true })).toBeVisible();
  await expect(
    page.getByText('Last updated: 10/31/2026, 8:15:00 PM', { exact: true }),
  ).toBeVisible();
  await expect(page.locator('time')).toHaveAttribute(
    'datetime',
    fixture.utc_boundary.coverage_start!,
  );
  await expect(page.locator('time')).toHaveText('10/31/2026, 8:15:00 PM');
  await expect(page.getByText('$0.00', { exact: true })).toHaveCount(0);
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
});

test('Pinecone keeps subcent observed usage separate from the monthly commitment and polls cached data', async ({
  page,
  fixtureAPI,
}) => {
  await page.clock.install();
  fixtureAPI.get('/api/costs/aws', ready(aws));
  fixtureAPI.get('/api/costs/pinecone', ready(fixture.observed));
  await page.goto('/costs');
  await expect(page.getByText('$12.25', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Pinecone', exact: true }).click();
  await expect(
    page.locator('strong').filter({ hasText: '$0.00006' }),
  ).toBeVisible();
  await expect(page.getByText('10 RU', { exact: true })).toBeVisible();
  await expect(
    page.getByText(/Standard monthly commitment: USD 50/),
  ).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Configured pricing source' }),
  ).toHaveAttribute('href', 'https://www.pinecone.io/pricing/');
  const refreshed = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/costs/pinecone',
  );
  await page.clock.runFor(15_000);
  await refreshed;
  expect(
    fixtureAPI.requests.filter(
      (request) => new URL(request.url).pathname === '/api/costs/aws',
    ),
  ).toHaveLength(1);
  expect(
    fixtureAPI.requests.filter(
      (request) => new URL(request.url).pathname === '/api/costs/pinecone',
    ),
  ).toHaveLength(2);
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
});

test('Pinecone reports stale snapshots and missing-price quantities without substituting zero', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/costs/aws', ready(aws));
  fixtureAPI.get('/api/costs/pinecone', {
    state: 'stale',
    report: fixture.no_price,
    error: {
      code: 'metrics_unavailable',
      message: 'Monitoring is temporarily unavailable.',
    },
  });
  await page.goto('/costs');
  await page.getByRole('button', { name: 'Pinecone', exact: true }).click();
  await expect(
    page.getByText('Monitoring is temporarily unavailable.', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Cost unavailable for this period', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/Configure dated cloud\/region prices/),
  ).toBeVisible();
  await expect(page.getByText('10 RU', { exact: true })).toBeVisible();
  await expect(page.getByText('$0.00', { exact: true })).toHaveCount(0);
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('Pinecone selection rejects a delayed response from the previous AWS view', async ({
  page,
  fixtureAPI,
}) => {
  let release!: (value: unknown) => void;
  const deferred = new Promise((resolve) => {
    release = resolve;
  });
  fixtureAPI.mock(
    'GET',
    '/api/costs/aws',
    async (_request: APIRequest) => await deferred,
  );
  fixtureAPI.get('/api/costs/pinecone', ready(fixture.observed));
  await page.goto('/costs');
  await page.getByRole('button', { name: 'Pinecone', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Observed usage estimate', exact: true }),
  ).toBeVisible();
  release(ready(aws));
  await expect(
    page.getByText('Synthetic AWS billing account', { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.locator('strong').filter({ hasText: '$0.00006' }),
  ).toBeVisible();
});
