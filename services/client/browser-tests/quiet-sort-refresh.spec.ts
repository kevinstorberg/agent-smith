import { test, expect } from './fixtures';
import { harnessFixture } from './harnessFixture';
import { auditFixture } from './operationsFixture';
import { resultSortingRows } from '../src/pages/__tests__/resultSortingFixture';
import { enlargeComputedText } from './typography';

const cases = [
  {
    name: 'Rules',
    path: '/harness/rules?sort=name_desc',
    api: '/api/harness/items/rule',
    header: 'Name',
    row: harnessFixture({ name: 'Retained row' }),
  },
  {
    name: 'Plans',
    path: '/plans?sort=title_desc',
    api: '/api/plans',
    header: 'Title',
    row: {
      id: 1,
      title: 'Retained row',
      status: 'draft',
      project: 'work',
      created_at: '2026-01-01T12:00:00Z',
      updated_at: '2026-01-01T12:00:00Z',
    },
  },
  {
    name: 'Results',
    path: '/evals?sort=scenario_desc',
    api: '/api/evals',
    header: 'Scenario',
    row: { ...resultSortingRows[0], scenario: 'Retained row' },
  },
  {
    name: 'Audit',
    path: '/audit?sort=tool_desc',
    api: '/api/audit/events',
    header: 'Tool',
    row: { ...auditFixture(), tool_name: 'Retained row' },
  },
];

for (const resource of cases) {
  test(`${resource.name} keeps pending header sorts quiet and stationary at normal and doubled text`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    fixtureAPI.get('/api/audit/counts', { claude: 1, codex: 0, gemini: 0 });
    fixtureAPI.get('/api/evals/categories', ['rules']);
    fixtureAPI.get('/api/evals/subcategories', ['core']);
    fixtureAPI.get('/api/evals/facets', { scenarios: [], models: [] });
    fixtureAPI.get('/api/evals/chart/average', []);
    for (const scale of [1, 2]) {
      const response = { items: [resource.row], total: 1 };
      fixtureAPI.get(resource.api, response);
      await page.goto(resource.path);
      const row = page.getByText('Retained row', { exact: true });
      await expect(row).toBeVisible();
      if (scale === 2) await enlargeComputedText(page);
      const table = page.getByRole('table');
      const header = table.getByRole('columnheader', {
        name: resource.header,
        exact: true,
      });
      const button = header.getByRole('button');
      await button.scrollIntoViewIfNeeded();
      await button.focus();
      const before = {
        header: await header.boundingBox(),
        table: await table.boundingBox(),
      };
      let finish!: (value: typeof response) => void;
      const pending = new Promise<typeof response>((resolve) => {
        finish = resolve;
      });
      fixtureAPI.get(resource.api, () => pending);
      await button.press('Enter');
      await expect(table).toHaveAttribute('aria-busy', 'true');
      await expect(page.getByText(/Showing previous results/)).toHaveCount(0);
      await expect(page.getByText('Loading...', { exact: true })).toHaveCount(
        0,
      );
      await expect(page.getByText('Updating…', { exact: true })).toHaveCount(0);
      await expect(row).toBeVisible();
      await expect(button).toBeFocused();
      await expect(header).not.toHaveAttribute('aria-sort');
      const during = {
        header: await header.boundingBox(),
        table: await table.boundingBox(),
      };
      expect(during.header!.y).toBeCloseTo(before.header!.y, 4);
      expect(during.table!.height).toBeCloseTo(before.table!.height, 4);
      await page.screenshot({
        path: testInfo.outputPath(`${resource.name}-${scale}x-pending.png`),
      });
      finish(response);
      await expect(table).toHaveAttribute('aria-busy', 'false');
      await expect(button).toBeFocused();
      expect((await header.boundingBox())!.y).toBeCloseTo(before.header!.y, 4);
    }
    expect(
      fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
    ).toEqual([]);
  });
}
