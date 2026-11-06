import { test, expect, type APIRequest } from './fixtures';
import { enlargeComputedText } from './typography';
import {
  expectControlContained,
  expectControlReachable,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { resultSortingRows } from '../src/pages/__tests__/resultSortingFixture';

for (const scale of [1, 2]) {
  test(`Results order the complete server set and keep all headers readable at ${scale}x`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
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
    await page.goto('/evals?category=rules&subcategory=core&q=release&keep=1');
    await expect(page.getByText('Scenario 30', { exact: true })).toBeVisible();
    expect(
      await page.getByRole('combobox', { name: 'Sort results' }).count(),
    ).toBe(0);
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByText('Scenario 20', { exact: true })).toBeVisible();
    const chartReads = fixtureAPI.requests.filter(
      (entry) => new URL(entry.url).pathname === '/api/evals/chart/average',
    ).length;
    if (scale === 2) await enlargeComputedText(page);
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
      await expectControlReachable(button);
      await expectControlContained(button, header);
      await expectControlContained(button, region);
      const geometry = await button.evaluate((node) => {
        const label = node.querySelector('.sortable-header-label')!;
        const icon = node
          .querySelector('.sortable-header-icon')!
          .getBoundingClientRect();
        const range = document.createRange();
        range.selectNodeContents(label);
        return {
          fragments: [...range.getClientRects()].map((rect) => ({
            right: rect.right,
          })),
          right: label.getBoundingClientRect().right,
          iconLeft: icon.left,
        };
      });
      expect(geometry.fragments).toHaveLength(1);
      expect(geometry.fragments[0].right).toBeLessThanOrEqual(
        geometry.iconLeft,
      );
      expect(geometry.iconLeft - geometry.right).toBeLessThanOrEqual(16);
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
    await expectDocumentContained(page);
    await expectMainContained(page);
    if (scale === 2) {
      await enlargeComputedText(page);
      await region.evaluate((node) => {
        node.scrollLeft = 0;
      });
      await page.screenshot({
        path: testInfo.outputPath('results-headers-2x.png'),
      });
    }
  });
}
