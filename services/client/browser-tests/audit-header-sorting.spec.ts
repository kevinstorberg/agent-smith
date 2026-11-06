import { test, expect, type APIRequest } from './fixtures';
import { auditFixture } from './operationsFixture';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';

const rows = Array.from({ length: 30 }, (_, index) => ({
  ...auditFixture(),
  id: index + 1,
  tool_name: `Release ${String(index + 1).padStart(2, '0')}`,
  project: 'work',
  duration_ms: index + 1,
  created_at: `2026-01-${String(index + 1).padStart(2, '0')}T12:00:00Z`,
}));
const data = (tool: string) => ({
  items: [{ ...rows[0], tool_name: tool }],
  total: 30,
});

test('Audit header directions order the global result at page zero and survive reload', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/audit/counts', { claude: 30, codex: 0, gemini: 0 });
  fixtureAPI.get('/api/audit/events', ({ url }: APIRequest) => {
    const sort = url.searchParams.get('sort') || 'newest';
    const ascending = sort.endsWith('_asc') || sort === 'oldest';
    const ordered = ascending ? rows : [...rows].reverse();
    const offset = Number(url.searchParams.get('offset') || 0),
      limit = Number(url.searchParams.get('limit') || 10);
    return { items: ordered.slice(offset, offset + limit), total: 30 };
  });
  await page.goto(
    '/audit?q=release&agent=claude&status=success&project=work&offset=20&keep=1',
  );
  await expect(
    page.getByRole('link', { name: 'Release 10', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('combobox', { name: 'Sort', exact: true }),
  ).toHaveCount(0);
  for (const [label, values] of [
    ['Tool', ['tool_asc', 'tool_desc']],
    ['Status', ['status_asc', 'status_desc']],
    ['Agent', ['agent_asc', 'agent_desc']],
    ['Duration', ['duration', 'duration_asc']],
    ['Project', ['project_asc', 'project_desc']],
    ['Time', ['newest', 'oldest']],
  ] as const) {
    const header = page.getByRole('columnheader', { name: label, exact: true });
    for (const sort of values) {
      await header.getByRole('button').click();
      await expect
        .poll(() => new URL(page.url()).searchParams.get('sort'))
        .toBe(sort);
      const asc = sort.endsWith('_asc') || sort === 'oldest';
      await expect(
        page.getByRole('link', {
          name: asc ? 'Release 01' : 'Release 30',
          exact: true,
        }),
      ).toBeVisible();
      await expect(header).toHaveAttribute(
        'aria-sort',
        asc ? 'ascending' : 'descending',
      );
      const query = new URL(
        fixtureAPI.requests
          .filter(
            (entry) => new URL(entry.url).pathname === '/api/audit/events',
          )
          .at(-1)!.url,
      ).searchParams;
      expect(Object.fromEntries(query)).toMatchObject({
        q: 'release',
        agent: 'claude',
        status: 'success',
        project: 'work',
        limit: '10',
        offset: '0',
        sort,
      });
      expect(new URL(page.url()).searchParams.get('keep')).toBe('1');
      await page.reload();
      await expect(header).toHaveAttribute(
        'aria-sort',
        asc ? 'ascending' : 'descending',
      );
    }
  }
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Audit native keyboard headers retain focus and ignore stale completions', async ({
  page,
  fixtureAPI,
}) => {
  let resolveAsc!: (value: ReturnType<typeof data>) => void,
    resolveDesc!: (value: ReturnType<typeof data>) => void;
  const asc = new Promise<ReturnType<typeof data>>((resolve) => {
      resolveAsc = resolve;
    }),
    desc = new Promise<ReturnType<typeof data>>((resolve) => {
      resolveDesc = resolve;
    });
  fixtureAPI.get('/api/audit/counts', { claude: 1, codex: 0, gemini: 0 });
  fixtureAPI.get('/api/audit/events', ({ url }: APIRequest) =>
    url.searchParams.get('sort') === 'tool_asc'
      ? asc
      : url.searchParams.get('sort') === 'tool_desc'
        ? desc
        : data('Initial row'),
  );
  await page.goto('/audit');
  await expect(
    page.getByRole('link', { name: 'Initial row', exact: true }),
  ).toBeVisible();
  const header = page.getByRole('columnheader', { name: 'Tool', exact: true }),
    button = header.getByRole('button');
  await button.focus();
  await page.keyboard.press('Enter');
  await expect
    .poll(() =>
      fixtureAPI.requests.some(
        (entry) => new URL(entry.url).searchParams.get('sort') === 'tool_asc',
      ),
    )
    .toBe(true);
  await expect(page.locator('.audit-results')).toHaveAttribute(
    'aria-busy',
    'true',
  );
  await expect(page.getByRole('table')).toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('[aria-sort]')).toHaveCount(0);
  await expect(button).toBeFocused();
  await page.keyboard.press('Space');
  await expect
    .poll(() =>
      fixtureAPI.requests.some(
        (entry) => new URL(entry.url).searchParams.get('sort') === 'tool_desc',
      ),
    )
    .toBe(true);
  resolveDesc(data('Accepted descending'));
  await expect(
    page.getByRole('link', { name: 'Accepted descending', exact: true }),
  ).toBeVisible();
  const stale = page.waitForResponse(
    (response) =>
      new URL(response.url()).searchParams.get('sort') === 'tool_asc',
  );
  resolveAsc(data('Stale ascending'));
  await (await stale).finished();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  await expect(
    page.getByRole('link', { name: 'Stale ascending', exact: true }),
  ).toHaveCount(0);
  await expect(header).toHaveAttribute('aria-sort', 'descending');
  await expect(button).toBeFocused();
});

test('Audit headers stay readable with adjacent arrows at normal and doubled text', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  fixtureAPI.get('/api/audit/counts', { claude: 1, codex: 0, gemini: 0 });
  fixtureAPI.get('/api/audit/events', data('Visible row'));
  await page.goto('/audit');
  await expect(
    page.getByRole('link', { name: 'Visible row', exact: true }),
  ).toBeVisible();
  await expectSortableHeaderLayout(page, testInfo, {
    table: page.getByRole('table'),
    scrollRegion: page.getByRole('region', {
      name: 'Audit events',
      exact: true,
    }),
    labels: ['Tool', 'Status', 'Agent', 'Duration', 'Project', 'Time'],
    artifactPrefix: 'audit-headers',
    assertLayout: async () => {
      const measurements = await page
        .locator('.audit-list-table .sortable-header-button')
        .evaluateAll((buttons) =>
          buttons.map((button) => {
            const label = button
              .querySelector('.sortable-header-label')!
              .getBoundingClientRect();
            const icon = button
              .querySelector('.sortable-header-icon')!
              .getBoundingClientRect();
            return {
              gap: icon.x - label.right,
              vertical: Math.abs(
                label.y + label.height / 2 - icon.y - icon.height / 2,
              ),
            };
          }),
        );
      for (const measurement of measurements) {
        expect(measurement.gap).toBeLessThanOrEqual(12);
        expect(measurement.vertical).toBeLessThanOrEqual(1);
      }
    },
  });
});
