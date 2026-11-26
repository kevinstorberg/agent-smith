import { test, expect, type APIRequest } from './fixtures';
import type { ActionItemQueueRoot } from '../src/api';
import { actionItem, deferred } from '../src/pages/__tests__/actionItemFixture';
import {
  epicGroup,
  queuePage,
  taskEntry,
  taskPage,
} from '../src/pages/__tests__/actionItemEpicFixture';
import { epicReference } from '../src/utils/actionItemEpics';
import { openItemActions } from './actionItemDisclosures';
import {
  expectControlContained,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { enlargeComputedText } from './typography';
import type { Page } from '@playwright/test';

async function expectWorkspaceHeaders(page: Page) {
  const table = page.locator('.action-item-grouped-table');
  if (page.viewportSize()!.width <= 1100) {
    await expect(
      page.getByRole('combobox', { name: 'Sort by', exact: true }),
    ).toBeVisible();
    await expect(table.locator(':scope > thead button')).toHaveCount(0);
    return;
  }
  const header = table.locator(':scope > thead');
  const title = header.getByRole('columnheader', {
    name: 'Title',
    exact: true,
  });
  const headingX = (await title
    .locator('.sortable-header-label')
    .boundingBox())!.x;
  const textStarts = await page
    .locator('.action-item-title')
    .evaluateAll((buttons) =>
      buttons.map((button) => {
        const nodes = document.createTreeWalker(button, NodeFilter.SHOW_TEXT);
        let node = nodes.nextNode();
        while (node) {
          if (
            node.textContent?.trim() &&
            !node.parentElement?.closest('[aria-hidden="true"]')
          ) {
            const range = document.createRange();
            range.selectNodeContents(node);
            return range.getClientRects()[0].x;
          }
          node = nodes.nextNode();
        }
        throw new Error('A task title must contain readable text');
      }),
    );
  for (const start of textStarts)
    expect(
      Math.abs(start - headingX),
      'Title header and task text must share one content anchor',
    ).toBeLessThanOrEqual(2);
  for (const label of ['Order', 'Title']) {
    const column = header.getByRole('columnheader', {
      name: label,
      exact: true,
    });
    await expectControlContained(
      column.getByRole('button', { name: label, exact: true }),
      column,
    );
  }
}

test('the visible Action Items view includes Epic children and paginates tasks', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  const clinical = epicGroup(10, [
    actionItem(2, {
      title: "Fix unmapped SDOH screenings in HealthCall's JSON",
      priority: 2,
      tags: ['healthcall', 'mapping', 'sdoh'],
    }),
    actionItem(3, {
      title:
        'Prepare the staging SFTP environment and allowlist the customer IP',
      priority: 3,
      tags: ['johnson-county', 'rainbow', 'sftp', 'staging'],
      due_at: '2026-12-01T17:00:00Z',
    }),
  ]);
  clinical.epic.title = 'Clinical integrations and mapping';
  clinical.epic.position = 2;
  const security = epicGroup(11, [actionItem(5, { priority: 5 })]);
  security.epic.title = 'Security and SOC 2';
  security.epic.position = 4;
  const later = Array.from({ length: 11 }, (_, index) => {
    const group = epicGroup(20 + index, [
      actionItem(20 + index, { priority: 6 + index }),
    ]);
    group.epic.title = `Workstream ${index + 1}`;
    group.epic.position = index + 5;
    return group;
  });
  const standalone = queuePage({
    items: [actionItem(1), actionItem(4, { priority: 4 })],
    total: 2,
  }).items;
  if (standalone[1].kind !== 'item')
    throw new Error('Expected a standalone task');
  standalone[1].position = 3;
  const roots: ActionItemQueueRoot[] = [
    standalone[0],
    clinical,
    standalone[1],
    security,
    ...later,
  ];
  const tasks = roots.flatMap((root, rootIndex) =>
    root.kind === 'epic'
      ? root.children.map((entry) =>
          taskEntry(entry.item, {
            parent: root.epic,
            rootIndex,
            position: entry.position,
          }),
        )
      : [
          taskEntry(root.item, {
            parent: null,
            rootIndex,
            position: root.position,
          }),
        ],
  );
  fixtureAPI.get('/api/action-items/projects', {
    items: [{ id: 1, name: 'Work', created_at: '2026-11-01T12:00:00Z' }],
    total: 1,
  });
  fixtureAPI.get('/api/action-items/queue', ({ url }: APIRequest) => {
    const offset = Number(url.searchParams.get('offset') ?? 0);
    const limit = Number(url.searchParams.get('limit') ?? 10);
    if (url.searchParams.get('kind') === 'task')
      return taskPage({
        items: tasks.slice(offset, offset + limit),
        total: tasks.length,
        root_total: roots.length,
      });
    const entries =
      url.searchParams.get('kind') === 'epic'
        ? roots.filter((root) => root.kind === 'epic')
        : roots;
    return {
      items: entries.slice(offset, offset + limit),
      total: entries.length,
      matching_count: tasks.length,
    };
  });
  await page.goto('/action-items');
  await expect(
    page.getByRole('region', {
      name: `Epic ${clinical.epic.title}`,
      exact: true,
    }),
  ).toBeVisible();
  const main = page.locator('#main-content');
  for (const label of ['All', 'Epics', 'Action Items'])
    await expectControlContained(
      page.getByRole('button', { name: label, exact: true }),
      main,
    );
  await expectControlContained(
    page.getByRole('combobox', { name: 'Status' }),
    main,
  );
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectWorkspaceHeaders(page);
  await page.screenshot({
    path: testInfo.outputPath('workspace-groups-1x.png'),
    fullPage: true,
  });
  await page.screenshot({
    path: testInfo.outputPath('workspace-viewport-1x.png'),
  });
  const viewport = page.viewportSize()!;
  if (viewport.width === 1440) {
    await page.setViewportSize({ width: 2586, height: 1282 });
    await expectWorkspaceHeaders(page);
    await page.screenshot({
      path: testInfo.outputPath('workspace-wide-1x.png'),
    });
    await page.setViewportSize(viewport);
  }
  const restore = await enlargeComputedText(page, 2, { restorable: true });
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectWorkspaceHeaders(page);
  await page.screenshot({
    path: testInfo.outputPath('workspace-groups-2x.png'),
    fullPage: true,
  });
  await page.screenshot({
    path: testInfo.outputPath('workspace-viewport-2x.png'),
  });
  if (viewport.width === 1440) {
    await page.setViewportSize({ width: 2586, height: 1282 });
    await expectWorkspaceHeaders(page);
    await page.screenshot({
      path: testInfo.outputPath('workspace-wide-2x.png'),
    });
    await page.setViewportSize(viewport);
  }
  await restore?.();
  await page.getByRole('button', { name: 'Action Items', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Action Items', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('region', { name: /^Epic / })).toHaveCount(0);
  await expect(
    page.getByRole('button', {
      name: clinical.children[0].item.title,
      exact: true,
    }),
  ).toBeVisible();
  const row = page.locator('.action-item-row').filter({
    has: page.getByRole('button', {
      name: clinical.children[0].item.title,
      exact: true,
    }),
  });
  await expect(
    row.getByText(`Epic: ${clinical.epic.title}`, { exact: true }),
  ).toBeVisible();
  await expect(row.getByRole('button', { name: /^Reorder / })).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Task 30', exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.get('kind')).toBe('task');
  expect(new URL(page.url()).searchParams.get('offset')).toBe('10');
  await page.getByRole('button', { name: 'Epics', exact: true }).click();
  expect(new URL(page.url()).searchParams.get('offset')).toBe('0');
  await expect(
    page.getByRole('region', {
      name: `Epic ${clinical.epic.title}`,
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toHaveCount(0);
  expect(
    fixtureAPI.requests.filter((request) => request.method !== 'GET'),
  ).toEqual([]);
});

test('a filtered middle child moves to the true top and bottom of its own Epic', async ({
  page,
  fixtureAPI,
}) => {
  const middle = actionItem(2, { title: 'Only matching task', priority: 2 });
  const group = epicGroup(10, [actionItem(1), middle, actionItem(3)]);
  const order = [1, 2, 3];
  const writes: unknown[] = [];
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items/queue', () => {
    const entry = group.children.find((child) => child.item.id === 2)!;
    entry.position = order.indexOf(2) + 1;
    return {
      items: [{ ...group, children: [entry], matching_count: 1 }],
      total: 1,
      matching_count: 1,
    };
  });
  fixtureAPI.mock(
    'POST',
    '/api/action-items/queue/move',
    ({ request }: APIRequest) => {
      const body = request.postDataJSON();
      writes.push(body);
      expect(body).toEqual({
        source: { kind: 'item', id: 2, expected_revision: middle.revision },
        parent: epicReference(group.epic),
        edge: writes.length === 1 ? 'top' : 'bottom',
      });
      order.splice(order.indexOf(2), 1);
      if (body.edge === 'top') order.unshift(2);
      else order.push(2);
      middle.revision++;
      group.epic.revision++;
      group.epic.cohort = `cohort-10-edge-${writes.length}`;
      return { saved: true };
    },
  );
  await page.goto('/action-items?q=Only%20matching');
  await openItemActions(page, middle.title);
  const top = page.getByRole('button', {
    name: `Move ${middle.title} to top of Epic`,
    exact: true,
  });
  const bottom = page.getByRole('button', {
    name: `Move ${middle.title} to bottom of Epic`,
    exact: true,
  });
  await expect(top).toBeEnabled();
  await expect(bottom).toBeEnabled();
  await top.click();
  await expect.poll(() => order).toEqual([2, 1, 3]);
  await openItemActions(page, middle.title);
  await expect(top).toBeDisabled();
  await expect(bottom).toBeEnabled();
  await bottom.click();
  await expect.poll(() => order).toEqual([1, 3, 2]);
  await openItemActions(page, middle.title);
  await expect(bottom).toBeDisabled();
  expect(
    fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
  ).toHaveLength(2);
});

test('Move out of Epic stays available after catalog failure and preserves the task', async ({
  page,
  fixtureAPI,
}) => {
  const item = actionItem(2);
  const group = epicGroup(10, [item]);
  const gate = deferred<ReturnType<typeof actionItem>>();
  let removed = false;
  const bodies: unknown[] = [];
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get(
    '/api/action-items/epics',
    { detail: 'Catalog unavailable' },
    503,
  );
  fixtureAPI.get('/api/action-items/queue', ({ url }: APIRequest) =>
    url.searchParams.get('kind') === 'task'
      ? taskPage({
          items: [
            taskEntry(item, {
              parent: removed ? null : group.epic,
              rootIndex: 0,
              position: 1,
            }),
          ],
          total: 1,
          root_total: 1,
        })
      : {
          items: [
            {
              ...group,
              children: removed ? [] : group.children,
              matching_count: removed ? 0 : 1,
            },
          ],
          total: 1,
          matching_count: removed ? 0 : 1,
        },
  );
  fixtureAPI.mock(
    'POST',
    '/api/action-items/2/epic',
    ({ request }: APIRequest) => {
      const body = request.postDataJSON();
      bodies.push(body);
      expect(body).toEqual({
        expected_revision: item.revision,
        expected_parent: epicReference(group.epic),
        destination: null,
      });
      return gate.promise;
    },
  );
  await page.goto('/action-items?kind=epic');
  await openItemActions(page, item.title);
  await page
    .getByRole('button', { name: `Move ${item.title} to Epic`, exact: true })
    .click();
  await expect(page.getByText(/Could not load Epics/)).toBeVisible();
  await page
    .getByRole('group', { name: `Epic for ${item.title}`, exact: true })
    .getByRole('button', { name: 'Cancel', exact: true })
    .click();
  await openItemActions(page, item.title);
  const moveOut = page.getByRole('button', {
    name: `Move ${item.title} out of Epic`,
    exact: true,
  });
  await expect(moveOut).toBeEnabled();
  await moveOut.evaluate((button) => {
    (button as HTMLButtonElement).click();
    (button as HTMLButtonElement).click();
  });
  await expect.poll(() => bodies.length).toBe(1);
  await expect(
    page.getByRole('combobox', { name: 'Status', exact: true }),
  ).toBeDisabled();
  removed = true;
  group.epic.revision++;
  group.epic.cohort = 'cohort-10-without-task';
  gate.resolve(item);
  await expect(
    page.getByRole('button', { name: item.title, exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole('status').filter({ hasText: /out of|standalone/i }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Action Items', exact: true }).click();
  const row = page.locator('.action-item-row').filter({
    has: page.getByRole('button', { name: item.title, exact: true }),
  });
  await expect(row).toBeVisible();
  await expect(
    row.getByRole('button', {
      name: `Move ${item.title} out of Epic`,
      exact: true,
    }),
  ).toHaveCount(0);
  expect(bodies).toHaveLength(1);
  expect(
    fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
  ).toHaveLength(1);
});

test('a stale parent rejects Move out of Epic without hiding or deleting the task', async ({
  page,
  fixtureAPI,
}) => {
  const item = actionItem(2);
  const group = epicGroup(10, [item]);
  const bodies: unknown[] = [];
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items/queue', () => ({
    items: [group],
    total: 1,
    matching_count: 1,
  }));
  fixtureAPI.mock(
    'POST',
    '/api/action-items/2/epic',
    ({ request }: APIRequest) => {
      bodies.push(request.postDataJSON());
      return {
        detail:
          'The Epic changed during review. Refresh before moving this task.',
      };
    },
    409,
  );
  await page.goto('/action-items');
  await openItemActions(page, item.title);
  await page
    .getByRole('button', {
      name: `Move ${item.title} out of Epic`,
      exact: true,
    })
    .click();
  await expect(page.getByRole('alert')).toContainText(
    'The Epic changed during review',
  );
  await expect(
    page
      .getByRole('region', { name: 'Epic Release', exact: true })
      .getByRole('button', { name: item.title, exact: true }),
  ).toBeVisible();
  expect(bodies).toEqual([
    {
      expected_revision: item.revision,
      expected_parent: epicReference(group.epic),
      destination: null,
    },
  ]);
  expect(
    fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
  ).toHaveLength(1);
});
