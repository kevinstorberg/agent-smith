import { test, expect } from './fixtures';
import { costSortingReport as report } from '../src/pages/__tests__/costSortingFixture';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';
test.beforeEach(async ({ fixtureAPI }) => {
  for (const provider of ['aws', 'pinecone'])
    fixtureAPI.get(`/api/costs/${provider}`, {
      state: 'ready',
      report: { ...report, provider },
    });
});
test('Cost headers sort complete independent reports without provider calls', async ({
  page,
  fixtureAPI,
}) => {
  await page.goto('/costs');
  await expect(page.getByText('Ten', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Pinecone', exact: true }).click();
  await expect(page.getByText('Read two', { exact: true })).toBeVisible();
  const reads = fixtureAPI.requests.filter((r) =>
    new URL(r.url).pathname.startsWith('/api/costs/'),
  ).length;
  const costs = page.getByRole('region', {
    name: 'Costs by service table',
    exact: true,
  });
  const cost = costs.getByRole('button', { name: 'Cost', exact: true });
  await cost.focus();
  await cost.press('Enter');
  await expect(costs.locator('tbody tr').first()).toContainText('Credit');
  await expect(cost).toBeFocused();
  await cost.press('Space');
  await expect(costs.locator('tbody tr').first()).toContainText('Ten');
  const usage = page.getByRole('region', {
    name: 'Observed usage table',
    exact: true,
  });
  const amount = usage.getByRole('button', {
    name: 'Observed amount',
    exact: true,
  });
  await amount.click();
  await expect(usage.locator('tbody tr').first()).toContainText('Read two');
  await expect(usage.locator('tbody tr').last()).toContainText('Unknown');
  await amount.click();
  await expect(usage.locator('tbody tr').first()).toContainText('Write ten');
  await expect(usage.locator('tbody tr').last()).toContainText('Unknown');
  const daily = page.getByRole('region', {
    name: 'Daily costs table',
    exact: true,
  });
  await daily
    .getByRole('button', { name: 'Billing day (UTC)', exact: true })
    .click();
  await expect(daily.locator('tbody tr').first()).toContainText('2026-11-01');
  await expect(costs.locator('tbody tr').first()).toContainText('Ten');
  expect(
    fixtureAPI.requests.filter((r) =>
      new URL(r.url).pathname.startsWith('/api/costs/'),
    ),
  ).toHaveLength(reads);
  expect(fixtureAPI.requests.filter((r) => r.method !== 'GET')).toEqual([]);
});
for (const font of ['computed', 'Arial'])
  for (const [regionName, labels] of [
    ['Observed usage table', ['Metric', 'Observed amount']],
    ['Costs by service table', ['Service', 'Cost']],
    ['Daily costs table', ['Billing day (UTC)', 'Cost']],
  ] as const)
    test(`${regionName} remains readable with ${font} at normal and doubled text`, async ({
      page,
    }, info) => {
      await page.goto('/costs');
      await page.getByRole('button', { name: 'Pinecone', exact: true }).click();
      await expect(page.getByText('Read two', { exact: true })).toBeVisible();
      if (font === 'Arial')
        await page.addStyleTag({
          content: '*{font-family:Arial,sans-serif!important;}',
        });
      const region = page.getByRole('region', {
        name: regionName,
        exact: true,
      });
      await expectSortableHeaderLayout(page, info, {
        table: region.getByRole('table'),
        scrollRegion: region,
        labels,
        artifactPrefix: `cost-${regionName.split(' ')[0].toLowerCase()}-${font.toLowerCase()}`,
      });
    });
