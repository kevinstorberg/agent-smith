import { test, expect, type APIRequest } from './fixtures';
import { expectMainContained } from './geometry';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';
import { resultSortingRows } from '../src/pages/__tests__/resultSortingFixture';

test.beforeEach(async ({ fixtureAPI }) => {
  fixtureAPI.get('/api/evals/categories', ['rules']);
  fixtureAPI.get('/api/evals/subcategories', ['core']);
  fixtureAPI.get('/api/evals/facets', { scenarios: [], models: [] });
  fixtureAPI.get(
    '/api/evals/chart/average',
    resultSortingRows.map((row) => ({
      id: row.id,
      timestamp: row.timestamp,
      score: row.score_avg,
    })),
  );
});

for (const font of ['default', 'Arial']) {
  test(
    'Results headers order the complete server set at normal and doubled ' +
      font +
      ' text',
    async ({ page, fixtureAPI }, testInfo) => {
      fixtureAPI.get('/api/evals', ({ url }: APIRequest) => {
        const ordered =
          url.searchParams.get('sort') === 'scenario_asc'
            ? resultSortingRows
            : [...resultSortingRows].reverse();
        const offset = Number(url.searchParams.get('offset') || 0);
        const limit = Number(url.searchParams.get('limit') || 10);
        return {
          items: ordered.slice(offset, offset + limit),
          total: ordered.length,
        };
      });
      await page.goto(
        '/evals?category=rules&subcategory=core&q=release&keep=1',
      );
      await expect(
        page.getByText('Scenario 30', { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole('combobox', { name: 'Sort results' }),
      ).toHaveCount(0);
      await page.getByRole('button', { name: 'Next', exact: true }).click();
      await expect(
        page.getByText('Scenario 20', { exact: true }),
      ).toBeVisible();
      const chartReads = fixtureAPI.requests.filter(
        (entry) => new URL(entry.url).pathname === '/api/evals/chart/average',
      ).length;
      const region = page.getByRole('region', {
        name: 'Results list',
        exact: true,
      });
      const table = region.getByRole('table');
      for (const [label, first, second] of [
        ['Scenario', 'scenario_asc', 'scenario_desc'],
        ['Time', 'newest', 'oldest'],
        ['Category', 'category_asc', 'category_desc'],
        ['Model', 'model_asc', 'model_desc'],
        ['Threshold', 'threshold_asc', 'threshold_desc'],
        ['Scores', 'score', 'score_asc'],
      ] as const) {
        const header = table.getByRole('columnheader', {
          name: label,
          exact: true,
        });
        const button = header.getByRole('button', { name: label, exact: true });
        await button.scrollIntoViewIfNeeded();
        for (const sort of [first, second]) {
          await button.focus();
          await button.press(sort === first ? 'Enter' : 'Space');
          await expect
            .poll(() => new URL(page.url()).searchParams.get('sort'))
            .toBe(sort);
          await expect(header).toHaveAttribute(
            'aria-sort',
            sort.endsWith('_asc') || sort === 'oldest'
              ? 'ascending'
              : 'descending',
          );
          await expect(table).toHaveAttribute('aria-busy', 'false');
          await expect(button).toBeFocused();
        }
        if (label === 'Scenario')
          await expect(
            page.getByText('Showing 1–10 of 30', { exact: true }),
          ).toBeVisible();
      }
      const reads = fixtureAPI.requests.filter(
        (entry) => new URL(entry.url).pathname === '/api/evals',
      );
      const sorted = new URL(
        reads.find(
          (entry) =>
            new URL(entry.url).searchParams.get('sort') === 'scenario_asc',
        )!.url,
      ).searchParams;
      expect(Object.fromEntries(sorted)).toMatchObject({
        eval_type: 'rules',
        subcategory: 'core',
        q: 'release',
        offset: '0',
      });
      expect(new URL(page.url()).searchParams.get('keep')).toBe('1');
      expect(
        fixtureAPI.requests.filter(
          (entry) => new URL(entry.url).pathname === '/api/evals/chart/average',
        ),
      ).toHaveLength(chartReads);
      expect(
        fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
      ).toHaveLength(0);
      await page.reload();
      await expect(
        table.getByRole('columnheader', { name: 'Scores' }),
      ).toHaveAttribute('aria-sort', 'ascending');
      const labels = [
        'Time',
        'Category',
        'Scenario',
        'Model',
        'Threshold',
        'Scores',
      ];
      if (font === 'Arial')
        await page.addStyleTag({
          content: ':root { --font: Arial, sans-serif; }',
        });
      if (font === 'Arial')
        await expect(table.getByRole('button').first()).toHaveCSS(
          'font-family',
          'Arial, sans-serif',
        );
      await expectSortableHeaderLayout(page, testInfo, {
        table,
        scrollRegion: region,
        labels,
        artifactPrefix: 'results-sort-' + font.toLowerCase(),
        fullyVisibleHeaders: labels,
        assertLayout: async () => expectMainContained(page),
      });
    },
  );
}

test('Results preserve native focus, reject stale orders, and keep empty/error headers available', async ({
  page,
  fixtureAPI,
}) => {
  const response = (scenario: string) => ({
    items: [{ ...resultSortingRows[0], scenario }],
    total: 30,
  });
  let finishAsc!: (value: ReturnType<typeof response>) => void;
  let finishDesc!: (value: ReturnType<typeof response>) => void;
  const asc = new Promise<ReturnType<typeof response>>((resolve) => {
    finishAsc = resolve;
  });
  const desc = new Promise<ReturnType<typeof response>>((resolve) => {
    finishDesc = resolve;
  });
  fixtureAPI.get('/api/evals', ({ url }: APIRequest) =>
    url.searchParams.get('sort') === 'scenario_asc'
      ? asc
      : url.searchParams.get('sort') === 'scenario_desc'
        ? desc
        : response('Initial accepted row'),
  );
  await page.goto('/evals');
  await expect(
    page.getByText('Initial accepted row', { exact: true }),
  ).toBeVisible();
  const table = page.getByRole('table');
  const scenario = table.getByRole('columnheader', {
    name: 'Scenario',
    exact: true,
  });
  const button = scenario.getByRole('button');
  await button.focus();
  await button.press('Enter');
  await expect(table).toHaveAttribute('aria-busy', 'true');
  await expect(table.locator('[aria-sort]')).toHaveCount(0);
  await expect(button).toBeFocused();
  await button.press('Space');
  await expect
    .poll(
      () =>
        fixtureAPI.requests.filter(
          (entry) =>
            new URL(entry.url).searchParams.get('sort') === 'scenario_desc',
        ).length,
    )
    .toBe(1);
  finishDesc(response('Current descending row'));
  await expect(
    page.getByText('Current descending row', { exact: true }),
  ).toBeVisible();
  const stale = page.waitForResponse(
    (reply) => new URL(reply.url()).searchParams.get('sort') === 'scenario_asc',
  );
  finishAsc(response('Obsolete ascending row'));
  await (await stale).finished();
  await expect(
    page.getByText('Obsolete ascending row', { exact: true }),
  ).toHaveCount(0);
  await expect(scenario).toHaveAttribute('aria-sort', 'descending');
  await expect(button).toBeFocused();
  fixtureAPI.get('/api/evals', { detail: 'Order unavailable' }, 503);
  const model = table
    .getByRole('columnheader', { name: 'Model', exact: true })
    .getByRole('button');
  await model.click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(table).toHaveAttribute('aria-busy', 'false');
  await expect(table.locator('[aria-sort]')).toHaveCount(0);
  await expect(model).toBeFocused();
  fixtureAPI.get('/api/evals', { items: [], total: 0 });
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(
    page.getByText('No eval runs found', { exact: true }),
  ).toBeVisible();
  await expect(table.getByRole('button')).toHaveCount(6);
  await expect(
    table.getByRole('columnheader', { name: 'Model', exact: true }),
  ).toHaveAttribute('aria-sort', 'ascending');
  expect(
    fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
  ).toHaveLength(0);
});
