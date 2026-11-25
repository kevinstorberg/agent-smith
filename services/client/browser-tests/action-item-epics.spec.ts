import { chooseEpic, expectEpicSelection } from './epicPicker';
import {
  expectActionItemSort,
  selectActionItemSort,
} from './actionItemSorting';
import { test, expect, type APIRequest } from './fixtures';
import type {
  ActionItemEpicCreate,
  ActionItemQueueMove,
  ActionItemQueueRoot,
} from '../src/api';
import { actionItem, deferred } from '../src/pages/__tests__/actionItemFixture';
import {
  epicGroup,
  queuePage,
} from '../src/pages/__tests__/actionItemEpicFixture';
import {
  expectControlContained,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { enlargeComputedText } from './typography';
import { openEpicActions, openItemActions } from './actionItemDisclosures';

test('Epics support create, singleton membership, collapse, rename, and removal that keeps tasks', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  let roots: ActionItemQueueRoot[] = [
    queuePage({ items: [actionItem(1)], total: 1 }).items[0],
    epicGroup(10),
    queuePage({ items: [actionItem(4)], total: 1 }).items[0],
  ];
  const writes: unknown[] = [];
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  const sync = () =>
    roots.forEach((root, index) => {
      if (root.kind === 'item') root.position = index + 1;
      else {
        root.epic.position = index + 1;
        root.children.forEach((child, i) => {
          child.position = i + 1;
        });
        root.matching_count = root.children.length;
        root.total_count = root.children.length;
      }
    });
  fixtureAPI.get('/api/action-items/queue', ({ url }: APIRequest) => {
    sync();
    const limit = Number(url.searchParams.get('limit') ?? 10);
    const offset = Number(url.searchParams.get('offset') ?? 0);
    const ordered =
      url.searchParams.get('sort') === 'manual_desc'
        ? [...roots].reverse()
        : roots;
    return {
      items: ordered.slice(offset, offset + limit),
      total: roots.length,
      matching_count: roots.reduce(
        (count, root) =>
          count + (root.kind === 'item' ? 1 : root.children.length),
        0,
      ),
    };
  });
  fixtureAPI.get('/api/action-items/epics', () => ({
    items: roots.flatMap((root) => (root.kind === 'epic' ? [root.epic] : [])),
  }));
  fixtureAPI.mock(
    'POST',
    '/api/action-items/epics',
    ({ request }: APIRequest) => {
      const body = request.postDataJSON() as ActionItemEpicCreate;
      writes.push(body);
      expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
      const group = epicGroup(20, []);
      group.epic.title = body.title;
      roots.push(group);
      sync();
      return group.epic;
    },
  );
  fixtureAPI.mock(
    'POST',
    '/api/action-items/1/epic',
    ({ request }: APIRequest) => {
      const body = request.postDataJSON();
      writes.push(body);
      expect(body).toMatchObject({
        expected_revision: 1,
        expected_parent: null,
        destination: { id: 20, expected_revision: 3, cohort: 'cohort-20' },
      });
      const entry = roots.find(
        (root) => root.kind === 'item' && root.item.id === 1,
      )!;
      if (entry.kind !== 'item') throw new Error('Expected standalone item');
      roots = roots.filter((root) => root !== entry);
      const group = roots.find(
        (root) => root.kind === 'epic' && root.epic.id === 20,
      )!;
      if (group.kind !== 'epic') throw new Error('Expected Epic');
      group.children.push({ ...entry, parent_epic_id: 20 });
      group.epic.revision++;
      group.epic.cohort = 'cohort-20-member';
      sync();
      return entry.item;
    },
  );
  fixtureAPI.mock(
    'PATCH',
    '/api/action-items/epics/20',
    ({ request }: APIRequest) => {
      const body = request.postDataJSON();
      writes.push(body);
      const root = roots.find(
        (root) => root.kind === 'epic' && root.epic.id === 20,
      )!;
      if (root.kind !== 'epic') throw new Error('Expected Epic');
      expect(body.expected_revision).toBe(root.epic.revision);
      root.epic = {
        ...root.epic,
        title: body.title,
        revision: root.epic.revision + 1,
      };
      return root.epic;
    },
  );
  fixtureAPI.mock(
    'DELETE',
    '/api/action-items/epics/20',
    ({ request }: APIRequest) => {
      const index = roots.findIndex(
        (root) => root.kind === 'epic' && root.epic.id === 20,
      );
      const root = roots[index];
      if (root.kind !== 'epic') throw new Error('Expected Epic');
      expect(request.postDataJSON()).toEqual({
        expected_revision: root.epic.revision,
        cohort: root.epic.cohort,
      });
      roots.splice(
        index,
        1,
        ...root.children.map((child) => ({ ...child, parent_epic_id: null })),
      );
      sync();
      return { deleted: true, id: 20 };
    },
  );
  await page.goto('/action-items');
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'New Epic', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Epic name', exact: true })
    .fill('Launch');
  await page.getByRole('button', { name: 'Save Epic', exact: true }).click();
  const group = page.getByRole('region', { name: 'Epic Launch', exact: true });
  await expect(group).toBeVisible();
  await expect(
    group.getByText('Showing 0 of 0 action items', { exact: true }),
  ).toBeVisible();
  await openItemActions(page, 'Task 1');
  await page
    .getByRole('button', { name: 'Move Task 1 to Epic', exact: true })
    .click();
  await page
    .getByRole('button', { name: 'Move to Epic', exact: true })
    .waitFor({ state: 'visible' });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath('epic-membership-picker.png'),
    fullPage: true,
  });
  await chooseEpic(
    page.getByRole('button', { name: 'Move to Epic', exact: true }),
    '20',
  );
  await expect(
    group.getByRole('button', { name: 'Task 1', exact: true }),
  ).toBeVisible();
  await expect(
    group.getByText('Showing 1 of 1 action items', { exact: true }),
  ).toBeVisible();
  await group.getByRole('button', { name: 'Launch', exact: true }).click();
  await expect(
    group.getByRole('button', { name: 'Task 1', exact: true }),
  ).toHaveCount(0);
  await group.getByRole('button', { name: 'Launch', exact: true }).click();
  await openEpicActions(page, 'Launch');
  await group.getByRole('button', { name: 'Rename Epic', exact: true }).click();
  await group
    .getByRole('textbox', { name: 'Epic name', exact: true })
    .fill('Launch checklist');
  await group.getByRole('button', { name: 'Save Epic', exact: true }).click();
  const renamed = page.getByRole('region', {
    name: 'Epic Launch checklist',
    exact: true,
  });
  await expect(renamed).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath('epic-singleton.png'),
    fullPage: true,
  });
  await enlargeComputedText(page);
  await expectDocumentContained(page);
  await expectMainContained(page);
  for (const control of await renamed.getByRole('button').all())
    await expectControlContained(control, page.locator('main'));
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath('epic-singleton-enlarged.png'),
    fullPage: true,
  });
  await openEpicActions(page, 'Launch checklist');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath('epic-menu-enlarged.png'),
    fullPage: true,
  });
  const beforeDelete = writes.length;
  page.once('dialog', (dialog) => {
    expect(dialog.message()).toBe(
      'Delete Epic “Launch checklist”? Its action items will be kept and moved out of the Epic.',
    );
    void dialog.dismiss();
  });
  await renamed
    .getByRole('button', { name: 'Delete Epic', exact: true })
    .click();
  expect(writes).toHaveLength(beforeDelete);
  await expect(renamed).toBeVisible();
  await openEpicActions(page, 'Launch checklist');
  page.once('dialog', (dialog) => {
    expect(dialog.message()).toBe(
      'Delete Epic “Launch checklist”? Its action items will be kept and moved out of the Epic.',
    );
    void dialog.accept();
  });
  await renamed
    .getByRole('button', { name: 'Delete Epic', exact: true })
    .click();
  await expect(renamed).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toBeVisible();
  expect(writes).toHaveLength(3);
  await expect(
    page.getByRole('button', { name: 'Show Epic', exact: true }),
  ).toHaveCount(0);
});

for (const collapsed of [false, true]) {
  test(`whole Epic moves with real keyboard and pointer when ${collapsed ? 'collapsed' : 'expanded'}`, async ({
    page,
    fixtureAPI,
  }) => {
    const group = epicGroup(10, [actionItem(2), actionItem(3)]);
    let roots: ActionItemQueueRoot[] = [
      ...queuePage({ items: [actionItem(1)], total: 1 }).items,
      group,
      ...queuePage({ items: [actionItem(4)], total: 1 }).items,
    ];
    const writes: ActionItemQueueMove[] = [];
    const keyboardRefresh = deferred<void>();
    let keyboardRefreshPending = false;
    fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
    fixtureAPI.get('/api/action-items/queue', async () => {
      if (writes.length === 1) {
        keyboardRefreshPending = true;
        await keyboardRefresh.promise;
      }
      return { items: roots, total: 3, matching_count: 4 };
    });
    fixtureAPI.mock(
      'POST',
      '/api/action-items/queue/move',
      ({ request }: APIRequest) => {
        const body = request.postDataJSON() as ActionItemQueueMove;
        writes.push(body);
        expect(body.source).toEqual({
          kind: 'epic',
          id: 10,
          expected_revision: 3,
          cohort: 'cohort-10',
        });
        expect(body.parent).toBeUndefined();
        roots = roots.filter((root) => root.kind !== 'epic');
        if (body.before) roots.unshift(group);
        else roots.push(group);
        return { saved: true };
      },
    );
    await page.goto('/action-items');
    const region = page.getByRole('region', {
      name: 'Epic Release',
      exact: true,
    });
    if (collapsed)
      await region
        .getByRole('button', { name: 'Release', exact: true })
        .click();
    const handle = region.getByRole('button', {
      name: 'Reorder Epic Release',
      exact: true,
    });
    try {
      await handle.focus();
      await page.keyboard.press('Space');
      await page.keyboard.press('ArrowUp');
      await page.keyboard.press('Space');
      await expect.poll(() => writes.length).toBe(1);
      expect(writes[0]).toMatchObject({
        before: { kind: 'item', id: 1, expected_revision: 1 },
      });
      await expect.poll(() => keyboardRefreshPending).toBe(true);
      await expect(handle).toBeDisabled();
    } finally {
      keyboardRefresh.resolve();
    }
    await expect
      .poll(() =>
        page
          .locator(
            '.action-item-grouped-table > tbody > tr[data-rfd-draggable-id]',
          )
          .evaluateAll((rows) =>
            rows.map((row) => row.getAttribute('data-rfd-draggable-id')),
          ),
      )
      .toEqual(['epic:10', 'item:1', 'item:4']);
    await expect(handle).toBeEnabled();
    const target = page.getByRole('button', {
      name: 'Reorder Task 4',
      exact: true,
    });
    await handle.scrollIntoViewIfNeeded();
    const from = await handle.boundingBox();
    expect(from).not.toBeNull();
    const targetRow = target.locator('xpath=ancestor::tr[1]');
    // Freeze the intended page slot before lift; SDK displacement moves the rendered target during scrolling.
    const targetPageRect = await targetRow.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return {
        x: bounds.x + window.scrollX,
        y: bounds.y + window.scrollY,
        width: bounds.width,
        height: bounds.height,
      };
    });
    expect(targetPageRect.width).toBeGreaterThan(0);
    expect(targetPageRect.height).toBeGreaterThan(0);
    await page.mouse.move(
      from!.x + from!.width / 2,
      from!.y + from!.height / 2,
    );
    await page.mouse.down();
    await page.mouse.move(
      from!.x + from!.width / 2,
      from!.y + from!.height / 2 + 8,
      { steps: 4 },
    );
    await expect(region.locator('xpath=ancestor::tr[1]')).toHaveCSS(
      'position',
      'fixed',
    );
    await targetRow.scrollIntoViewIfNeeded();
    // Keep the intended slot away from the viewport edge so auto-scroll cannot move it away from the pointer.
    await page.evaluate(
      (bounds) =>
        window.scrollTo({
          top: Math.max(
            0,
            bounds.y + bounds.height * 0.75 - window.innerHeight * 0.6,
          ),
          behavior: 'instant',
        }),
      targetPageRect,
    );
    const pointerDestination = await page.evaluate(
      (bounds) => ({
        x: bounds.x + 30 - window.scrollX,
        y: bounds.y + bounds.height * 0.75 - window.scrollY,
        viewportHeight: window.innerHeight,
      }),
      targetPageRect,
    );
    expect(pointerDestination.y).toBeGreaterThan(0);
    expect(pointerDestination.y).toBeLessThan(
      pointerDestination.viewportHeight,
    );
    await page.mouse.move(pointerDestination.x, pointerDestination.y, {
      steps: 20,
    });
    await expect(page.locator('[id^="rfd-announcement-"]')).toHaveText(
      /You have moved the item from position 1\s+to position 3/,
    );
    await page.mouse.up();
    await expect(page.locator('[id^="rfd-announcement-"]')).toHaveText(
      /You have dropped the item\.\s+You have moved the item from position 1\s+to position 3/,
    );
    await expect.poll(() => writes.length).toBe(2);
    expect(writes[1]).toMatchObject({
      after: { kind: 'item', id: 4, expected_revision: 1 },
    });
    await expect(
      region.getByRole('button', { name: 'Release', exact: true }),
    ).toHaveAttribute('aria-expanded', String(!collapsed));
    await expectDocumentContained(page);
  });
}

test('one visible header sorts Epic children and shows updated timestamps while preserving membership', async ({
  page,
  fixtureAPI,
}) => {
  const members = [
    actionItem(2, { title: 'Zulu work', updated_at: '2026-11-24T12:00:00Z' }),
    actionItem(3, { title: 'Alpha work', updated_at: '2026-11-25T12:00:00Z' }),
  ];
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items/queue', ({ url }: APIRequest) => {
    const sort = url.searchParams.get('sort');
    const children = [...members].sort((left, right) =>
      sort === 'title'
        ? left.title.localeCompare(right.title)
        : sort === 'updated'
          ? right.updated_at.localeCompare(left.updated_at)
          : left.updated_at.localeCompare(right.updated_at),
    );
    return {
      items: [
        epicGroup(10, children),
        ...queuePage({ items: [actionItem(4)], total: 1 }).items,
      ],
      total: 2,
      matching_count: 3,
    };
  });
  await page.goto('/action-items');
  const region = page.getByRole('region', {
    name: 'Epic Release',
    exact: true,
  });
  const table = region.getByRole('table', {
    name: 'Action items in Epic Release',
    exact: true,
  });
  const titles = table.locator('.action-item-title');
  await expect(
    table.getByRole('columnheader', { name: 'Updated', exact: true }),
  ).toHaveCount(1);
  await expect(table.locator('thead')).toHaveClass('visually-hidden');
  await expect(
    table.getByRole('button', { name: 'Title', exact: true }),
  ).toHaveCount(0);
  await expect(table.locator('.action-updated-cell').first()).toContainText(
    'Nov 24',
  );
  await selectActionItemSort(page, 'Title', 'title');
  await expect(titles).toHaveText(['›Alpha work', '›Zulu work']);
  await selectActionItemSort(page, 'Updated', 'updated');
  await expectActionItemSort(page, 'Updated', 'updated', 'descending');
  await selectActionItemSort(page, 'Updated', 'updated_asc');
  await expect(titles).toHaveText(['›Zulu work', '›Alpha work']);
  await expect(
    region.getByRole('button', { name: 'Task 4', exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Task 4', exact: true }),
  ).toBeVisible();
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('child keyboard ordering uses only its complete parent cohort and Escape makes no write', async ({
  page,
  fixtureAPI,
}) => {
  const group = epicGroup(10, [actionItem(2), actionItem(3)]);
  const writes: ActionItemQueueMove[] = [];
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items/queue', () => ({
    items: [group],
    total: 1,
    matching_count: 2,
  }));
  fixtureAPI.mock(
    'POST',
    '/api/action-items/queue/move',
    ({ request }: APIRequest) => {
      const body = request.postDataJSON() as ActionItemQueueMove;
      writes.push(body);
      expect(body).toEqual({
        source: { kind: 'item', id: 3, expected_revision: 1 },
        parent: { id: 10, expected_revision: 3, cohort: 'cohort-10' },
        before: { kind: 'item', id: 2, expected_revision: 1 },
      });
      group.children.reverse();
      return { saved: true };
    },
  );
  await page.goto('/action-items');
  const handle = page.getByRole('button', {
    name: 'Reorder Task 3',
    exact: true,
  });
  await handle.focus();
  await page.keyboard.press('Space');
  await page.keyboard.press('ArrowUp');
  await page.keyboard.press('Space');
  await expect.poll(() => writes.length).toBe(1);
  await handle.focus();
  await page.keyboard.press('Space');
  await page.keyboard.press('ArrowUp');
  await page.keyboard.press('Space');
  expect(writes).toHaveLength(1);
  await handle.focus();
  await page.keyboard.press('Space');
  await page.keyboard.press('Escape');
  expect(writes).toHaveLength(1);
});

test('ambiguous inline creation keeps its UUID and reviewed membership for an explicit retry', async ({
  page,
  fixtureAPI,
}) => {
  const pageData = queuePage({ items: [actionItem(1)], total: 1 });
  const requests: ActionItemEpicCreate[] = [];
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items/queue', pageData);
  fixtureAPI.get('/api/action-items/epics', { items: [] });
  fixtureAPI.mock(
    'POST',
    '/api/action-items/epics',
    ({ request }: APIRequest) => {
      requests.push(request.postDataJSON());
      return { detail: 'Synthetic uncertain response' };
    },
    504,
  );
  await page.goto('/action-items');
  await openItemActions(page, 'Task 1');
  await page
    .getByRole('button', { name: 'Move Task 1 to Epic', exact: true })
    .click();
  await chooseEpic(
    page.getByRole('button', { name: 'Move to Epic', exact: true }),
    'new',
  );
  await page
    .getByRole('textbox', { name: 'Epic name', exact: true })
    .fill('Retry group');
  await page.getByRole('button', { name: 'Save Epic', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(
    'Synthetic uncertain response',
  );
  await expect(
    page.getByRole('textbox', { name: 'Epic name', exact: true }),
  ).toHaveValue('Retry group');
  const name = page.getByRole('textbox', { name: 'Epic name', exact: true });
  await expect(name).toHaveAttribute('readonly');
  await name.focus();
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.type('Changed title');
  await expect(name).toHaveValue('Retry group');
  await page.getByRole('button', { name: 'Save Epic', exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]).toEqual(requests[0]);
  expect(requests[0]).toMatchObject({
    item_id: 1,
    membership: { expected_revision: 1, expected_parent: null },
  });
});

test('filtered whole-root edge movement preserves hidden membership and reports one stale conflict', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  const group = epicGroup(10, [actionItem(2)]);
  group.total_count = 8;
  const anchor = queuePage({ items: [actionItem(22)], total: 1 }).items[0];
  let writes = 0;
  const reads: URL[] = [];
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items/queue', ({ url }: APIRequest) => {
    reads.push(url);
    return {
      items:
        url.searchParams.get('sort') === 'manual_desc' ? [anchor] : [group],
      total: 2,
      matching_count: 2,
    };
  });
  fixtureAPI.mock(
    'POST',
    '/api/action-items/queue/move',
    ({ request }: APIRequest) => {
      writes++;
      expect(request.postDataJSON()).toEqual({
        source: {
          kind: 'epic',
          id: 10,
          expected_revision: 3,
          cohort: 'cohort-10',
        },
        after: { kind: 'item', id: 22, expected_revision: 1 },
      });
      return { detail: 'Synthetic changed hidden membership' };
    },
    409,
  );
  await page.goto('/action-items?project=Work&q=Task&tags=security&limit=10');
  const region = page.getByRole('region', {
    name: 'Epic Release',
    exact: true,
  });
  await expect(region.getByText('Showing 1 of 8 action items')).toBeVisible();
  await openItemActions(page, 'Task 2');
  await expect(
    region.getByRole('button', {
      name: 'Move Task 2 to top of Epic',
      exact: true,
    }),
  ).toBeDisabled();
  await page.keyboard.press('Escape');
  await openEpicActions(page, 'Release');
  await region
    .getByRole('button', { name: 'Move Epic Release to bottom', exact: true })
    .click();
  await expect(page.getByRole('alert')).toHaveCount(1);
  await expect(page.getByRole('alert')).toContainText(
    'Synthetic changed hidden membership',
  );
  await expect(
    region.getByRole('button', { name: 'Task 2', exact: true }),
  ).toBeVisible();
  expect(writes).toBe(1);
  const probe = reads.find((url) => url.searchParams.get('limit') === '1');
  expect(probe).toBeDefined();
  expect(Object.fromEntries(probe!.searchParams)).toMatchObject({
    project: 'Work',
    q: 'Task',
    tags: 'security',
    sort: 'manual_desc',
    offset: '0',
    limit: '1',
  });
  await page.screenshot({
    path: testInfo.outputPath('epic-filtered-stale.png'),
    fullPage: true,
  });
});

test('a failed membership selection stays canonical and permits the same explicit destination again', async ({
  page,
  fixtureAPI,
}) => {
  const source = epicGroup();
  const destination = { ...epicGroup(20).epic, title: 'Next group' };
  let attempts = 0;
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items/queue', {
    items: [source],
    total: 1,
    matching_count: 1,
  });
  fixtureAPI.get('/api/action-items/epics', {
    items: [source.epic, destination],
  });
  fixtureAPI.mock(
    'POST',
    '/api/action-items/2/epic',
    ({ request }: APIRequest) => {
      attempts++;
      expect(request.postDataJSON().destination.id).toBe(20);
      return { detail: 'Synthetic membership conflict' };
    },
    409,
  );
  await page.goto('/action-items');
  await openItemActions(page, 'Task 2');
  await page
    .getByRole('button', { name: 'Move Task 2 to Epic', exact: true })
    .click();
  const picker = page.getByRole('button', {
    name: 'Move to Epic',
    exact: true,
  });
  await chooseEpic(picker, '20');
  await expect(page.getByRole('alert')).toContainText(
    'Synthetic membership conflict',
  );
  await expectEpicSelection(picker, 'Release');
  await expect(picker).toBeEnabled();
  expect(attempts).toBe(1);
  await chooseEpic(picker, '20');
  await expect.poll(() => attempts).toBe(2);
  await expectEpicSelection(picker, 'Release');
});

test('an in-flight child content refresh preserves a structural whole-Epic drag', async ({
  page,
  fixtureAPI,
}) => {
  await page.clock.install();
  const original = epicGroup();
  const changed = epicGroup(10, [
    actionItem(2, { title: 'Updated child content', revision: 2 }),
  ]);
  const tail = queuePage({ items: [actionItem(4)], total: 1 }).items[0];
  const pending = deferred<unknown>();
  let reads = 0;
  let writes = 0;
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items/queue', () => {
    reads++;
    if (reads === 2) return pending.promise;
    return {
      items: writes ? [tail, changed] : [original, tail],
      total: 2,
      matching_count: 2,
    };
  });
  fixtureAPI.mock(
    'POST',
    '/api/action-items/queue/move',
    ({ request }: APIRequest) => {
      writes++;
      expect(request.postDataJSON().source).toEqual({
        kind: 'epic',
        id: 10,
        expected_revision: 3,
        cohort: 'cohort-10',
      });
      return { saved: true };
    },
  );
  await page.goto('/action-items');
  const handle = page.getByRole('button', {
    name: 'Reorder Epic Release',
    exact: true,
  });
  await expect(handle).toBeEnabled();
  await page.clock.fastForward(15_000);
  await expect.poll(() => reads).toBe(2);
  await handle.focus();
  await page.keyboard.press('Space');
  const response = page.waitForResponse(
    (url) => new URL(url.url()).pathname === '/api/action-items/queue',
  );
  pending.resolve({ items: [changed, tail], total: 2, matching_count: 2 });
  await response;
  await page.clock.runFor(32);
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Space');
  await expect.poll(() => writes).toBe(1);
  await expect(
    page.getByRole('button', { name: 'Updated child content', exact: true }),
  ).toBeVisible();
});
