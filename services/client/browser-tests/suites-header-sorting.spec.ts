import { test, expect, type APIRequest } from './fixtures';
import { expectControlContained, expectMainContained } from './geometry';
import { enlargeComputedText } from './typography';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';
import { suiteSortingRows } from '../src/pages/__tests__/suiteSortingFixture';

for (const font of ['default', 'Arial']) {
  test(
    'Eval Suites headers order the full collection with readable ' +
      font +
      ' text',
    async ({ page, fixtureAPI }, testInfo) => {
      fixtureAPI.get('/api/eval-configs/suites', ({ url }: APIRequest) => {
        const rows =
          url.searchParams.get('sort') === 'scenario_count_desc'
            ? [...suiteSortingRows].reverse()
            : suiteSortingRows;
        const offset = Number(url.searchParams.get('offset') || 0);
        const limit = Number(url.searchParams.get('limit') || 10);
        return {
          items: rows.slice(offset, offset + limit),
          total: rows.length,
        };
      });
      await page.goto('/eval-configs?q=release&enabled=false&keep=1');
      await expect(page.getByText('Suite 01', { exact: true })).toBeVisible();
      await expect(
        page.getByRole('combobox', { name: 'Sort eval suites' }),
      ).toHaveCount(0);
      await page.getByRole('button', { name: 'Next', exact: true }).click();
      await expect(page.getByText('Suite 11', { exact: true })).toBeVisible();
      const region = page.getByRole('region', {
        name: 'Eval suites',
        exact: true,
      });
      const table = region.getByRole('table');
      for (const [label, first, second] of [
        ['Scenarios', 'scenario_count_asc', 'scenario_count_desc'],
        ['Name', 'name', 'name_desc'],
        ['Type', 'type_asc', 'type_desc'],
        ['Enabled', 'enabled_asc', 'enabled_desc'],
        ['Updated', 'updated', 'updated_asc'],
      ] as const) {
        const header = table.getByRole('columnheader', {
          name: label,
          exact: true,
        });
        const button = header.getByRole('button');
        await button.scrollIntoViewIfNeeded();
        for (const sort of [first, second]) {
          await button.focus();
          await button.press(sort === first ? 'Enter' : 'Space');
          await expect
            .poll(() => new URL(page.url()).searchParams.get('sort'))
            .toBe(sort);
          await expect(table).toHaveAttribute('aria-busy', 'false');
          await expect(header).toHaveAttribute(
            'aria-sort',
            sort.endsWith('_desc') || sort === 'updated'
              ? 'descending'
              : 'ascending',
          );
          await expect(button).toBeFocused();
        }
        if (label === 'Scenarios') {
          await expect(
            page.getByText('Suite 30', { exact: true }),
          ).toBeVisible();
          await expect(
            page.getByText('Showing 1–10 of 30', { exact: true }),
          ).toBeVisible();
        }
      }
      const sorted = fixtureAPI.requests.find(
        (entry) =>
          new URL(entry.url).searchParams.get('sort') === 'scenario_count_desc',
      )!;
      expect(
        Object.fromEntries(new URL(sorted.url).searchParams),
      ).toMatchObject({
        q: 'release',
        enabled: 'false',
        enabled_only: 'false',
        offset: '0',
      });
      expect(
        fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
      ).toHaveLength(0);
      expect(new URL(page.url()).searchParams.get('keep')).toBe('1');
      await page.reload();
      await expect(
        table.getByRole('columnheader', { name: 'Updated' }),
      ).toHaveAttribute('aria-sort', 'ascending');
      if (font === 'Arial') {
        await page.addStyleTag({
          content: ':root { --font: Arial, sans-serif; }',
        });
        await expect(table.getByRole('button').first()).toHaveCSS(
          'font-family',
          'Arial, sans-serif',
        );
      }
      const labels = ['Name', 'Type', 'Scenarios', 'Enabled', 'Updated'];
      await expectSortableHeaderLayout(page, testInfo, {
        table,
        scrollRegion: region,
        labels,
        fullyVisibleHeaders: labels,
        artifactPrefix: 'suites-sort-' + font.toLowerCase(),
        assertLayout: async () => expectMainContained(page),
      });
    },
  );
}

test('Eval Suites preserve quiet pending rows and contained empty feedback through an error and retry', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/eval-configs/suites', {
    items: [suiteSortingRows[0]],
    total: 1,
  });
  await page.goto('/eval-configs');
  await expect(page.getByText('Suite 01', { exact: true })).toBeVisible();
  const region = page.getByRole('region', { name: 'Eval suites', exact: true });
  const table = region.getByRole('table');
  const button = table.getByRole('button', { name: 'Name', exact: true });
  let finish!: (value: { items: never[]; total: number }) => void;
  fixtureAPI.get(
    '/api/eval-configs/suites',
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await button.focus();
  const before = await table.boundingBox();
  await button.press('Enter');
  await expect(table).toHaveAttribute('aria-busy', 'true');
  await expect(page.getByText('Loading...', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Suite 01', { exact: true })).toBeVisible();
  await expect(table.getByRole('checkbox')).toBeDisabled();
  expect((await table.boundingBox())!.height).toBeCloseTo(before!.height, 4);
  finish({ items: [], total: 0 });
  const message = region.getByRole('status');
  await expect(message).toHaveText('No eval suites found');
  await expect(button).toBeFocused();
  for (const scale of [1, 2]) {
    if (scale === 2) await enlargeComputedText(page);
    for (const edge of ['start', 'end']) {
      await region.evaluate((node, edge) => {
        node.scrollLeft = edge === 'start' ? 0 : node.scrollWidth;
      }, edge);
      await expectControlContained(message, region);
      await expectMainContained(page);
    }
  }
  fixtureAPI.get('/api/eval-configs/suites', { detail: 'Unavailable' }, 503);
  await button.press('Enter');
  await expect(page.getByRole('alert')).toContainText(
    'Could not load eval suites.',
  );
  await expect(table).toHaveAttribute('aria-busy', 'false');
  fixtureAPI.get('/api/eval-configs/suites', { items: [], total: 0 });
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(message).toBeVisible();
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});
