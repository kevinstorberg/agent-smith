import { test, expect, type APIRequest } from './fixtures';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import {
  expectDocumentContained,
  expectMainContained,
  expectControlContained,
} from './geometry';
import { enlargeComputedText } from './typography';

test('projects persist independently and assignment leaves tags and status filters separate', async ({
  page,
  fixtureAPI,
}) => {
  const projects = [
    { id: 1, name: 'Work', created_at: '2026-11-01T12:00:00Z' },
    { id: 2, name: 'Other', created_at: '2026-11-01T12:00:00Z' },
    { id: 3, name: 'Unassigned', created_at: '2026-11-01T12:00:00Z' },
  ];
  let rows = [actionItem(1, { tags: ['security'] })];
  fixtureAPI.get('/api/action-items/projects', () => ({
    items: projects,
    total: projects.length,
  }));
  fixtureAPI.mock(
    'POST',
    '/api/action-items/projects',
    ({ request }: APIRequest) => {
      const saved = {
        id: projects.length + 1,
        name: request.postDataJSON().name as string,
        created_at: '2026-11-05T12:00:00Z',
      };
      projects.push(saved);
      return saved;
    },
  );
  fixtureAPI.get('/api/action-items', ({ url }: APIRequest) => {
    const params = url.searchParams;
    const items = rows.filter(
      (row) =>
        (!params.get('project') || row.project === params.get('project')) &&
        (params.get('unassigned') !== 'true' || row.project === null) &&
        (!params.get('status') ||
          params.get('status') === 'all' ||
          row.status === params.get('status')) &&
        params.getAll('tags').every((tag) => row.tags.includes(tag)),
    );
    return { items, total: items.length };
  });
  fixtureAPI.mock('POST', '/api/action-items', ({ request }: APIRequest) => {
    const body = request.postDataJSON();
    expect(body.project).toBe('Family / QA & café #1');
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
    const saved = actionItem(2, { ...body, priority: 2 });
    rows.push(saved);
    return saved;
  });
  fixtureAPI.get('/api/action-items/2', () => rows.find((row) => row.id === 2));
  fixtureAPI.mock('PATCH', '/api/action-items/2', ({ request }: APIRequest) => {
    const body = request.postDataJSON();
    const row = rows.find((row) => row.id === 2)!;
    expect(body.expected_revision).toBe(row.revision);
    const saved = { ...row, ...body, revision: row.revision + 1 };
    rows = rows.map((item) => (item.id === 2 ? saved : item));
    return saved;
  });
  await page.goto('/action-items');
  const groups = page.getByRole('tablist', { name: 'Action item projects' });
  await groups.getByRole('tab', { name: 'Work', exact: true }).click();
  await page.getByLabel('Tags', { exact: true }).fill('security');
  await expect
    .poll(() =>
      fixtureAPI.requests.some((entry) => {
        const url = new URL(entry.url);
        return (
          url.pathname === '/api/action-items' &&
          url.searchParams.get('project') === 'Work' &&
          url.searchParams.get('tags') === 'security'
        );
      }),
    )
    .toBe(true);
  await page
    .getByRole('tablist', { name: 'Action item status' })
    .getByRole('tab', { name: 'Completed' })
    .click();
  await expect(
    groups.getByRole('tab', { name: 'Work', exact: true }),
  ).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByLabel('Tags', { exact: true })).toHaveValue(
    'security',
  );
  await page
    .getByRole('tablist', { name: 'Action item status' })
    .getByRole('tab', { name: 'Open', exact: true })
    .click();
  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name').fill('  Family / QA & café #1  ');
  await page
    .getByRole('button', { name: 'Create project', exact: true })
    .click();
  const selected = groups.getByRole('tab', {
    name: 'Family / QA & café #1',
    exact: true,
  });
  await expect(selected).toHaveAttribute('aria-selected', 'true');
  await page.reload();
  await expect(selected).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('No open action items found.')).toBeVisible();
  await page
    .getByRole('link', { name: 'New action item', exact: true })
    .click();
  await expect(
    page.getByRole('combobox', { name: 'Project', exact: true }),
  ).toHaveValue('Family / QA & café #1');
  await page.getByLabel('Title', { exact: true }).fill('Created task');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Created task', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await page
    .getByRole('combobox', { name: 'Project', exact: true })
    .selectOption('Other');
  await page.getByLabel('Tags', { exact: true }).fill('urgent');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Edit', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await page
    .getByRole('combobox', { name: 'Project', exact: true })
    .selectOption('');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Edit', exact: true }),
  ).toBeVisible();
  await page.goto('/action-items?unassigned=true&tags=urgent');
  await expect(
    groups.getByRole('tab', { name: 'Unassigned', exact: true }),
  ).toHaveAttribute('aria-selected', 'true');
  await expect(
    groups.getByRole('tab', { name: 'Project: Unassigned', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Created task', exact: true }),
  ).toBeVisible();
  expect(rows.find((row) => row.id === 2)).toMatchObject({
    project: null,
    tags: ['urgent'],
    revision: 3,
    priority: 2,
  });
  await expectDocumentContained(page);
  await expectMainContained(page);
});

for (const scale of [1, 2]) {
  test(`all fifty project tabs remain keyboard reachable at ${scale}x text`, async ({
    page,
    fixtureAPI,
  }) => {
    const items = Array.from({ length: 50 }, (_, index) => ({
      id: index + 1,
      name: `Group ${String(index + 1).padStart(2, '0')}`,
      created_at: '2026-11-01T12:00:00Z',
    }));
    fixtureAPI.get('/api/action-items/projects', {
      items,
      total: items.length,
    });
    fixtureAPI.get('/api/action-items', { items: [], total: 0 });
    await page.goto('/action-items');
    const groups = page.getByRole('tablist', { name: 'Action item projects' });
    await expect(groups.getByRole('tab')).toHaveCount(52);
    if (scale === 2) await enlargeComputedText(page);
    await groups
      .getByRole('tab', { name: 'All projects', exact: true })
      .focus();
    await page.keyboard.press('End');
    const last = groups.getByRole('tab', { name: 'Group 50', exact: true });
    await expect(last).toBeFocused();
    await expect(last).toHaveAttribute('aria-selected', 'true');
    await expectControlContained(last, groups);
    await page.keyboard.press('Home');
    await expect(
      groups.getByRole('tab', { name: 'All projects', exact: true }),
    ).toBeFocused();
    await expectDocumentContained(page);
    await expectMainContained(page);
  });
}

test('a project-filtered keyboard drag keeps global priorities and anchored revision writes', async ({
  page,
  fixtureAPI,
}) => {
  const project = { id: 1, name: 'Work', created_at: '2026-11-01T12:00:00Z' };
  let rows = [actionItem(1, { priority: 3 }), actionItem(2, { priority: 7 })];
  fixtureAPI.get('/api/action-items/projects', { items: [project], total: 1 });
  fixtureAPI.get('/api/action-items', ({ url }: APIRequest) => {
    expect(url.searchParams.get('project')).toBe('Work');
    expect(url.searchParams.get('tags')).toBe('security');
    return { items: rows, total: rows.length };
  });
  let moves = 0;
  fixtureAPI.mock(
    'POST',
    '/api/action-items/1/move',
    ({ request }: APIRequest) => {
      expect(request.postDataJSON()).toEqual({
        expected_revision: 1,
        after_id: 2,
      });
      moves += 1;
      rows = [
        actionItem(2, { priority: 6 }),
        actionItem(1, { priority: 7, revision: 2 }),
      ];
      return rows[1];
    },
  );
  await page.goto('/action-items?project=Work&tags=security');
  await expect(page.getByLabel('Priority 3', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Priority 7', { exact: true })).toBeVisible();
  const handle = page.getByRole('button', {
    name: 'Reorder Task 1',
    exact: true,
  });
  await handle.focus();
  await page.keyboard.press('Space');
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toBeDisabled();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Space');
  await expect.poll(() => moves).toBe(1);
  await expect(page.getByLabel('Priority 6', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Priority 7', { exact: true })).toBeVisible();
  expect(
    await page
      .locator('tbody .action-item-title')
      .evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute('aria-label')),
      ),
  ).toEqual(['Task 2', 'Task 1']);
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toHaveAttribute('aria-selected', 'true');
  expect(
    fixtureAPI.requests.filter((request) => request.method === 'POST'),
  ).toHaveLength(1);
});
