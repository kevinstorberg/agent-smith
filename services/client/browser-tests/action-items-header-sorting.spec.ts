import { test, expect, type APIRequest } from './fixtures';
import { actionItem, deferred } from '../src/pages/__tests__/actionItemFixture';
import { profileFixture } from '../src/pages/__tests__/profileFixture';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';
import { expectControlContained, expectDocumentContained } from './geometry';
import { enlargeComputedText } from './typography';

const pairs = [
  ['Priority', 'manual', 'manual_desc'],
  ['Title', 'title', 'title_desc'],
  ['Project', 'project_asc', 'project_desc'],
  ['Tags', 'tags_asc', 'tags_desc'],
  ['Due date', 'due_asc', 'due_desc'],
] as const;
const topicResponse = (id: number, total = 25) => ({
  items: [{ ...actionItem(id), profile_id: profileFixture.id }],
  total,
  profile_id: profileFixture.id,
});
const response = (id: number, total = 25) => ({
  items: [actionItem(id)],
  total,
});

test('Action Items header toggles preserve filters, reset page two, and restore preferences without writes', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/action-items/projects', {
    items: [{ id: 1, name: 'Work', created_at: '2026-11-01T12:00:00Z' }],
    total: 1,
  });
  fixtureAPI.get('/api/action-items', ({ url }: APIRequest) =>
    response(url.searchParams.get('offset') === '10' ? 11 : 1),
  );
  await page.goto('/action-items?project=Work&tags=security&q=Task&keep=1');
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('combobox', { name: 'Sort', exact: true }),
  ).toHaveCount(0);
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Task 11', exact: true }),
  ).toBeVisible();
  const start = fixtureAPI.requests.length;
  const table = page.getByRole('table');
  await table.getByRole('button', { name: 'Title', exact: true }).click();
  await expect(
    table.getByRole('columnheader', { name: 'Title', exact: true }),
  ).toHaveAttribute('aria-sort', 'ascending');
  const reads = fixtureAPI.requests
    .slice(start)
    .filter((entry) => new URL(entry.url).pathname === '/api/action-items');
  expect(reads).toHaveLength(1);
  expect(Object.fromEntries(new URL(reads[0].url).searchParams)).toMatchObject({
    project: 'Work',
    tags: 'security',
    q: 'Task',
    offset: '0',
    limit: '10',
    sort: 'title',
  });
  for (const [label, ascending, descending] of pairs) {
    const button = table.getByRole('button', { name: label, exact: true });
    const orders = [ascending, descending];
    for (const sort of orders) {
      await button.click();
      await expect(button.locator('xpath=ancestor::th')).toHaveAttribute(
        'aria-sort',
        sort === ascending ? 'ascending' : 'descending',
      );
      expect(new URL(page.url()).searchParams.get('sort')).toBe(sort);
      expect(
        Object.fromEntries(new URL(page.url()).searchParams),
      ).toMatchObject({
        project: 'Work',
        tags: 'security',
        q: 'Task',
        keep: '1',
        offset: '0',
      });
    }
  }
  await page.reload();
  await expect(
    table
      .getByRole('button', { name: 'Due date', exact: true })
      .locator('xpath=ancestor::th'),
  ).toHaveAttribute('aria-sort', 'descending');
  await table.getByRole('button', { name: 'Priority', exact: true }).click();
  await expect(
    table
      .getByRole('button', { name: 'Priority', exact: true })
      .locator('xpath=ancestor::th'),
  ).toHaveAttribute('aria-sort', 'ascending');
  await expect(
    page.getByRole('button', { name: 'Reorder Task 1', exact: true }),
  ).toBeEnabled();
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Action Item keyboard sorts retain rows and focus, reject stale responses, and suppress refresh prose', async ({
  page,
  fixtureAPI,
}) => {
  const asc = deferred<ReturnType<typeof response>>();
  const desc = deferred<ReturnType<typeof response>>();
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items', ({ url }: APIRequest) =>
    url.searchParams.get('sort') === 'title'
      ? asc.promise
      : url.searchParams.get('sort') === 'title_desc'
        ? desc.promise
        : response(1),
  );
  await page.goto('/action-items');
  const table = page.getByRole('table');
  const title = table.getByRole('button', { name: 'Title', exact: true });
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toBeVisible();
  await title.focus();
  await page.keyboard.press('Enter');
  await expect(table).toHaveAttribute('aria-busy', 'true');
  await expect(
    page.getByText('Loading action items…', { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText(/Showing previous results|Reordering is unavailable/),
  ).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Complete Task 1', exact: true }),
  ).toBeDisabled();
  await expect(title).toBeFocused();
  await expect(table.locator('[aria-sort]')).toHaveCount(0);
  await page.keyboard.press('Space');
  await expect
    .poll(() =>
      fixtureAPI.requests.some(
        (entry) => new URL(entry.url).searchParams.get('sort') === 'title_desc',
      ),
    )
    .toBe(true);
  desc.resolve(response(2, 40));
  await expect(
    page.getByRole('button', { name: 'Task 2', exact: true }),
  ).toBeVisible();
  const oldResponse = page.waitForResponse(
    (entry) => new URL(entry.url()).searchParams.get('sort') === 'title',
  );
  asc.resolve(response(3, 99));
  await (await oldResponse).finished();
  await expect(title.locator('xpath=ancestor::th')).toHaveAttribute(
    'aria-sort',
    'descending',
  );
  await expect(
    page.getByRole('button', { name: 'Task 3', exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText('Showing 1–10 of 40', { exact: true }),
  ).toBeVisible();
  await expect(title).toBeFocused();
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

for (const scope of ['action-items', 'discussion-topics'] as const) {
  for (const font of ['default', 'Arial'] as const) {
    test(`${scope} sortable headers retain whole labels at actual 1x and 2x ${font} text`, async ({
      page,
      fixtureAPI,
    }, testInfo) => {
      if (scope === 'action-items') {
        fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
        fixtureAPI.get('/api/action-items', response(1, 1));
        await page.goto('/action-items');
      } else {
        fixtureAPI.get(`/api/profiles/${profileFixture.id}`, profileFixture);
        fixtureAPI.get(
          `/api/profiles/${profileFixture.id}/discussion-topics`,
          topicResponse(1, 1),
        );
        await page.goto(`/profiles/${profileFixture.id}?tab=topics`);
      }
      await expect(
        page.getByRole('button', { name: 'Task 1', exact: true }),
      ).toBeVisible();
      if (font === 'Arial')
        await page.addStyleTag({
          content: '* { font-family: Arial, sans-serif !important; }',
        });
      const region = page.getByRole('region', {
        name: `${scope === 'action-items' ? 'action items' : 'discussion topics'} list`,
        exact: true,
      });
      const labels =
        scope === 'action-items'
          ? pairs.map(([name]) => name)
          : ['Priority', 'Title', 'Tags', 'Updated'];
      await expectSortableHeaderLayout(page, testInfo, {
        table: region.getByRole('table'),
        scrollRegion: region,
        labels,
        fullyVisibleHeaders: labels,
        artifactPrefix: `${scope}-sort-${font.toLowerCase()}`,
      });
      expect(
        fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
      ).toEqual([]);
    });
  }
}

test('Empty Action Items keep usable headers and contained feedback at both horizontal ends with doubled text', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items', { items: [], total: 0 });
  await page.goto('/action-items');
  const region = page.getByRole('region', {
    name: 'action items list',
    exact: true,
  });
  const empty = region.getByText('No open action items found.', {
    exact: true,
  });
  await expect(empty).toBeVisible();
  await enlargeComputedText(page);
  for (const end of [false, true]) {
    await region.evaluate((node, end) => {
      node.scrollLeft = end ? node.scrollWidth : 0;
    }, end);
    await expectControlContained(empty, region);
    await expectDocumentContained(page);
  }
  const title = region.getByRole('button', { name: 'Title', exact: true });
  await title.click();
  await expect(title.locator('xpath=ancestor::th')).toHaveAttribute(
    'aria-sort',
    'ascending',
  );
});

test('Discussion Topic header sorting resets page two without leaking global project or due-date fields', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get(`/api/profiles/${profileFixture.id}`, profileFixture);
  const endpoint = `/api/profiles/${profileFixture.id}/discussion-topics`;
  fixtureAPI.get(endpoint, ({ url }: APIRequest) => ({
    ...topicResponse(url.searchParams.get('offset') === '10' ? 11 : 1),
    profile_id: profileFixture.id,
  }));
  await page.goto(`/profiles/${profileFixture.id}?tab=topics`);
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Task 11', exact: true }),
  ).toBeVisible();
  const start = fixtureAPI.requests.length;
  const table = page.getByRole('table');
  await table.getByRole('button', { name: 'Tags', exact: true }).click();
  await expect(
    table.getByRole('columnheader', { name: 'Tags', exact: true }),
  ).toHaveAttribute('aria-sort', 'ascending');
  const reads = fixtureAPI.requests
    .slice(start)
    .filter((entry) => new URL(entry.url).pathname === endpoint);
  expect(reads).toHaveLength(1);
  expect(Object.fromEntries(new URL(reads[0].url).searchParams)).toMatchObject({
    offset: '0',
    sort: 'tags_asc',
    status: 'open',
  });
  await expect(
    table.getByRole('button', { name: 'Project', exact: true }),
  ).toHaveCount(0);
  await expect(
    table.getByRole('button', { name: 'Due date', exact: true }),
  ).toHaveCount(0);
  await table.getByRole('button', { name: 'Updated', exact: true }).click();
  await expect(
    table.getByRole('columnheader', { name: 'Updated', exact: true }),
  ).toHaveAttribute('aria-sort', 'descending');
  await table.getByRole('button', { name: 'Updated', exact: true }).click();
  await expect(
    table.getByRole('columnheader', { name: 'Updated', exact: true }),
  ).toHaveAttribute('aria-sort', 'ascending');
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Explicit Action Item Retry announces its pending read without adding refresh words', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items', response(1));
  await page.goto('/action-items');
  const table = page.getByRole('table');
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toBeVisible();
  fixtureAPI.get('/api/action-items', { detail: 'Synthetic failed read' }, 500);
  await table.getByRole('button', { name: 'Title', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(
    'Could not refresh action items.',
  );
  await expect(table).toHaveAttribute('aria-busy', 'false');
  const retry = deferred<ReturnType<typeof response>>();
  fixtureAPI.get('/api/action-items', () => retry.promise);
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(table).toHaveAttribute('aria-busy', 'true');
  await expect(
    page.getByText('Loading action items…', { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toBeVisible();
  retry.resolve(response(2));
  await expect(
    page.getByRole('button', { name: 'Task 2', exact: true }),
  ).toBeVisible();
  await expect(
    table.getByRole('columnheader', { name: 'Title', exact: true }),
  ).toHaveAttribute('aria-sort', 'ascending');
  await expect(table).toHaveAttribute('aria-busy', 'false');
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});
