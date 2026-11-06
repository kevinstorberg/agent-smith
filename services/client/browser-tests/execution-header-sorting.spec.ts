import { test, expect, type APIRequest } from './fixtures';
import { jobFixture } from '../src/pages/__tests__/jobFixture';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';
const result = (status: string) => ({
  items: [
    {
      id: 1,
      job_id: 42,
      status,
      started_at: '2026-01-01T12:00:00Z',
      completed_at: null,
      result: { exit_code: 10 },
    },
  ],
  total: 30,
});
test.beforeEach(async ({ fixtureAPI }) => {
  fixtureAPI.get('/api/jobs/42', jobFixture);
  fixtureAPI.get('/api/jobs/42/executions', ({ url }: APIRequest) =>
    result(url.searchParams.get('sort') || 'started_desc'),
  );
});
test('Execution headers request global directions before pagination without changing job configuration', async ({
  page,
  fixtureAPI,
}) => {
  await page.goto('/jobs/42?tab=executions');
  const region = page.getByRole('region', {
    name: 'Job executions',
    exact: true,
  });
  await expect(region.getByText('started_desc', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  for (const [label, values] of [
    ['Status', ['status_asc', 'status_desc']],
    ['Started', ['started_desc', 'started_asc']],
    ['Completed', ['completed_desc', 'completed_asc']],
    ['Exit', ['exit_asc', 'exit_desc']],
  ] as const) {
    const header = region.getByRole('columnheader', {
      name: label,
      exact: true,
    });
    for (const sort of values) {
      await header.getByRole('button').click();
      await expect(region.getByText(sort, { exact: true })).toBeVisible();
      await expect(header).toHaveAttribute(
        'aria-sort',
        sort.endsWith('_asc') ? 'ascending' : 'descending',
      );
      const params = new URL(
        fixtureAPI.requests
          .filter((r) => new URL(r.url).pathname === '/api/jobs/42/executions')
          .at(-1)!.url,
      ).searchParams;
      expect(params.get('offset')).toBe('0');
    }
  }
  expect(fixtureAPI.requests.filter((r) => r.method !== 'GET')).toEqual([]);
});
for (const font of ['computed', 'Arial'])
  test(`Execution headers remain readable with ${font} at normal and doubled text`, async ({
    page,
  }, info) => {
    await page.goto('/jobs/42?tab=executions');
    const region = page.getByRole('region', {
      name: 'Job executions',
      exact: true,
    });
    await expect(
      region.getByText('started_desc', { exact: true }),
    ).toBeVisible();
    if (font === 'Arial')
      await page.addStyleTag({
        content: '*{font-family:Arial,sans-serif!important;}',
      });
    await expectSortableHeaderLayout(page, info, {
      table: region.getByRole('table'),
      scrollRegion: region,
      labels: ['Status', 'Started', 'Completed', 'Exit'],
      artifactPrefix: `execution-${font.toLowerCase()}`,
    });
  });
