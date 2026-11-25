import { test, expect, type APIRequest } from './fixtures';
import type { Locator } from '@playwright/test';
import type { ActionItemGroupedPage } from '../src/api';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import {
  epicGroup,
  queuePage,
} from '../src/pages/__tests__/actionItemEpicFixture';
import {
  openAdvancedFilters,
  openEpicActions,
  openItemActions,
  openProjectOptions,
} from './actionItemDisclosures';
import {
  expectControlReachable,
  expectControlContained,
  expectDialogContained,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { enlargeComputedText } from './typography';

async function expectEpicFrame(region: Locator) {
  const frame = await region.evaluate((element) => {
    const style = getComputedStyle(element);
    const heading = element.querySelector('.action-item-epic-heading')!;
    return {
      borders: [
        style.borderTopWidth,
        style.borderRightWidth,
        style.borderBottomWidth,
        style.borderLeftWidth,
      ].map(parseFloat),
      background: style.backgroundColor,
      headingBackground: getComputedStyle(heading).backgroundColor,
    };
  });
  for (const border of frame.borders) expect(border).toBeGreaterThan(0);
  expect(frame.headingBackground).not.toBe(frame.background);
  const heading = region.locator('.action-item-epic-heading');
  await expectControlContained(heading, region);
  const regionBounds = (await region.boundingBox())!;
  const headingBounds = (await heading.boundingBox())!;
  expect(headingBounds.y).toBeGreaterThanOrEqual(regionBounds.y);
  expect(headingBounds.y + headingBounds.height).toBeLessThanOrEqual(
    regionBounds.y + regionBounds.height,
  );
  const children = region.locator('.epic-children');
  if (await children.count()) {
    await expectControlContained(children, region);
    await expect(children).toHaveCSS('box-shadow', 'none');
    await expect(children.getByRole('table')).toHaveCSS('box-shadow', 'none');
    const lastChild = (await children
      .locator('tbody > tr')
      .last()
      .boundingBox())!;
    expect(lastChild.y).toBeGreaterThanOrEqual(
      headingBounds.y + headingBounds.height - 1,
    );
    expect(lastChild.y + lastChild.height).toBeLessThanOrEqual(
      regionBounds.y + regionBounds.height + 1,
    );
  }
}

for (const scale of [1, 2]) {
  test(`Action Items hierarchy and action disclosures remain usable at ${scale}x text`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    const title = 'Review deployment readiness and supporting project context';
    const standalone = queuePage({
      items: [
        actionItem(1),
        actionItem(4, {
          title: 'Transfer domain ownership before the current account closes',
        }),
      ],
      total: 2,
    });
    const group = epicGroup(10, [
      actionItem(2, {
        title,
        tags: ['platform', 'release-readiness', 'security'],
        due_at: '2026-12-01T17:00:00Z',
        updated_at: '2026-11-25T12:00:00Z',
      }),
      actionItem(3, {
        title: 'Confirm staging data mapping and customer handoff',
        tags: ['mapping', 'staging'],
      }),
    ]);
    group.epic.position = 2;
    const security = epicGroup(11, [
      actionItem(5, {
        title:
          'Complete the vendor risk review and attach the supporting assessment',
        tags: ['compliance', 'vendor-review'],
        due_at: '2026-12-04T17:00:00Z',
        updated_at: '2026-11-24T14:30:00Z',
      }),
    ]);
    security.epic.title = 'Security readiness';
    security.epic.position = 3;
    const empty = epicGroup(12, []);
    empty.epic.title = 'Future work';
    empty.epic.position = 4;
    fixtureAPI.get('/api/action-items/projects', {
      items: [{ id: 1, name: 'Work', created_at: '2026-11-01T12:00:00Z' }],
      total: 1,
    });
    fixtureAPI.get('/api/action-items/epics', {
      items: [group.epic, security.epic, empty.epic],
    });
    fixtureAPI.get('/api/action-items/queue', {
      items: [
        standalone.items[0],
        group,
        security,
        empty,
        { ...standalone.items[1], position: 5 },
      ],
      total: 5,
      matching_count: 5,
    });
    await page.goto('/action-items');
    const item = page.getByRole('button', { name: title, exact: true });
    const more = page.getByRole('button', {
      name: `More actions for ${title}`,
      exact: true,
    });
    await expect(item).toBeVisible();
    await expect(more).toBeEnabled();
    await expect(
      page.getByRole('button', { name: 'New Epic', exact: true }),
    ).toBeEnabled();
    let restoreText =
      scale === 2
        ? await enlargeComputedText(page, scale, { restorable: true })
        : null;
    const refreshText = async () => {
      if (!restoreText) return;
      await restoreText();
      restoreText = await enlargeComputedText(page, scale, {
        restorable: true,
      });
    };
    const type = page.getByRole('combobox', { name: 'Item type', exact: true });
    await expectControlContained(type, page.locator('#main-content'));
    await expectControlReachable(type);
    await page.evaluate(() =>
      window.scrollTo({ top: 0, left: 0, behavior: 'instant' }),
    );
    for (const region of await page.locator('.action-item-epic-group').all())
      await expectEpicFrame(region);
    if (page.viewportSize()!.width >= 1400) {
      await testInfo.attach('desktop-column-widths.json', {
        body: JSON.stringify(
          await page.locator('.action-item-row').evaluateAll((rows) =>
            rows.map((row) => ({
              width: row.getBoundingClientRect().width,
              columns: Array.from(row.querySelectorAll(':scope > td')).map(
                (cell) => ({
                  className: cell.className,
                  width: cell.getBoundingClientRect().width,
                  cssWidth: getComputedStyle(cell).width,
                }),
              ),
            })),
          ),
          null,
          2,
        ),
        contentType: 'application/json',
      });
      for (const row of await page.locator('.action-item-row').all()) {
        const rowBounds = (await row.boundingBox())!;
        const titleBounds = (await row.getByRole('cell').nth(1).boundingBox())!;
        expect(
          titleBounds.width,
          'Desktop titles retain at least 35% of each row at normal and enlarged text',
        ).toBeGreaterThanOrEqual(rowBounds.width * 0.35 - 2);
      }
    }
    await page.screenshot({
      path: testInfo.outputPath(`action-item-default-${scale}x.png`),
      fullPage: true,
    });
    await page.screenshot({
      path: testInfo.outputPath(`action-item-default-viewport-${scale}x.png`),
    });
    const root = page.locator('.action-item-grouped-table');
    const children = page.getByRole('table', {
      name: 'Action items in Epic Release',
      exact: true,
    });
    for (const label of ['Priority', 'Title', 'Tags', 'Due date', 'Updated']) {
      await expect(
        root.getByRole('button', { name: label, exact: true }),
      ).toHaveCount(1);
      await expect(
        children.getByRole('columnheader', {
          name: label === 'Tags' ? 'Project / Tags' : label,
          exact: true,
        }),
      ).toHaveCount(1);
    }
    await expect(
      children.getByRole('button', { name: 'Title', exact: true }),
    ).toHaveCount(0);
    const childHead = await children.locator('thead').boundingBox();
    expect(childHead).not.toBeNull();
    expect(childHead!.width).toBeLessThanOrEqual(1);
    expect(childHead!.height).toBeLessThanOrEqual(1);
    await expect(
      page.getByRole('button', { name: `Edit ${title}`, exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: 'New project', exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole('textbox', { name: 'Tags', exact: true }),
    ).toHaveCount(0);

    await expectControlReachable(more);
    await more.focus();
    await page.keyboard.press('Enter');
    const panel = page.getByRole('group', {
      name: `More actions for ${title}`,
      exact: true,
    });
    await expect(panel).toBeVisible();
    await expect(item).toHaveAttribute('aria-expanded', 'false');
    await expectDialogContained(panel);
    await panel
      .getByRole('button', { name: `Edit ${title}`, exact: true })
      .focus();
    await page.keyboard.press('Escape');
    await expect(panel).toBeHidden();
    await expect(more).toBeFocused();

    await openItemActions(page, title);
    await expect(more).toBeFocused();
    await testInfo.attach('open-action-focus.json', {
      body: JSON.stringify(
        await page.evaluate(() => ({
          tag: document.activeElement?.tagName,
          label: document.activeElement?.getAttribute('aria-label'),
          text: document.activeElement?.textContent,
        })),
      ),
      contentType: 'application/json',
    });
    await page.screenshot({
      path: testInfo.outputPath(`action-item-menu-${scale}x.png`),
      fullPage: true,
    });
    await page.screenshot({
      path: testInfo.outputPath(`action-item-menu-viewport-${scale}x.png`),
    });
    const search = page.getByRole('searchbox', {
      name: 'Search action items',
      exact: true,
    });
    await search.click();
    await expect(panel).toBeHidden();
    await expect(search).toBeFocused();

    const epic = await openEpicActions(page, 'Release');
    const epicPanel = page.getByRole('group', {
      name: 'Actions for Epic Release',
      exact: true,
    });
    await expectDialogContained(epicPanel);
    for (const label of [
      'Move Epic Release to top',
      'Move Epic Release to bottom',
      'Rename Epic',
      'Remove Epic',
    ]) {
      await expectControlReachable(
        epicPanel.getByRole('button', { name: label, exact: true }),
      );
    }
    await epicPanel
      .getByRole('button', { name: 'Rename Epic', exact: true })
      .focus();
    await page.keyboard.press('Escape');
    await expect(epic).toBeFocused();
    await expect(
      page.getByRole('button', { name: 'Release', exact: true }),
    ).toHaveAttribute('aria-expanded', 'true');

    await openEpicActions(page, 'Release');
    await epicPanel
      .getByRole('button', { name: 'Rename Epic', exact: true })
      .click();
    const epicRegion = page.getByRole('region', {
      name: 'Epic Release',
      exact: true,
    });
    const rename = epicRegion.locator('.epic-name-form');
    await expect(
      rename.getByRole('textbox', { name: 'Epic name', exact: true }),
    ).toHaveValue('Release');
    await refreshText();
    const identity = epicRegion.getByRole('button', {
      name: 'Release',
      exact: true,
    });
    await expectControlContained(identity, epicRegion);
    expect(
      await identity.evaluate((element) => {
        const text = Array.from(element.childNodes).find(
          (node) =>
            node.nodeType === Node.TEXT_NODE &&
            node.textContent?.trim() === 'Release',
        );
        if (!text)
          throw new Error('Epic title must remain present while renaming');
        const range = document.createRange();
        range.selectNode(text);
        return Array.from(range.getClientRects()).filter(
          (rect) => rect.width > 0,
        ).length;
      }),
      'The short Epic title must stay readable rather than collapsing into separate characters',
    ).toBe(1);
    for (const control of await rename.locator('input, button').all()) {
      await expectControlContained(control, epicRegion);
      await expectControlReachable(control);
    }
    await expectDocumentContained(page);
    await expectMainContained(page);
    await page.screenshot({
      path: testInfo.outputPath(`epic-rename-viewport-${scale}x.png`),
    });
    await rename.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(epic).toBeFocused();

    await openItemActions(page, title);
    await panel
      .getByRole('button', { name: `Move ${title} to Epic`, exact: true })
      .click();
    const picker = page.getByRole('group', {
      name: `Epic for ${title}`,
      exact: true,
    });
    const destination = picker.getByRole('combobox', {
      name: 'Move to Epic',
      exact: true,
    });
    await expect(destination).toBeEnabled();
    await expect(destination).toHaveValue('10');
    await expectDialogContained(panel);
    await expectControlContained(destination, panel);
    await destination.selectOption('new');
    await expect(
      picker.getByRole('textbox', { name: 'Epic name', exact: true }),
    ).toBeVisible();
    await refreshText();
    for (const control of await picker.locator('input, select, button').all()) {
      await expectControlContained(control, panel);
      await expectControlReachable(control);
    }
    await expectDocumentContained(page);
    await expectMainContained(page);
    await page.screenshot({
      path: testInfo.outputPath(`epic-picker-viewport-${scale}x.png`),
    });
    await picker.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.keyboard.press('Escape');

    const projectOptions = await openProjectOptions(page);
    const projectPanel = page.getByRole('group', {
      name: 'Project options',
      exact: true,
    });
    await expectDialogContained(projectPanel);
    await expectControlReachable(
      projectPanel.getByRole('button', { name: 'New project', exact: true }),
    );
    await expectControlReachable(
      projectPanel.getByRole('link', { name: 'Manage projects', exact: true }),
    );
    await expect(
      projectPanel.getByRole('button', { name: 'Delete project', exact: true }),
    ).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(projectOptions).toBeFocused();
    await page.getByRole('tab', { name: 'Work', exact: true }).click();
    await openProjectOptions(page);
    await expect(
      projectPanel.getByRole('button', { name: 'Delete project', exact: true }),
    ).toBeVisible();
    await page.keyboard.press('Escape');
    await openAdvancedFilters(page);
    await refreshText();
    await expectControlReachable(
      page.getByRole('textbox', { name: 'Tags', exact: true }),
    );
    await page.screenshot({
      path: testInfo.outputPath(`action-item-hierarchy-${scale}x.png`),
      fullPage: true,
    });
    await testInfo.attach('action-items-overflow.json', {
      body: JSON.stringify(
        await page.locator('#main-content *').evaluateAll((elements) => {
          const main = document
            .querySelector('#main-content')!
            .getBoundingClientRect();
          return elements
            .filter(
              (element) =>
                element.getClientRects().length &&
                element.getBoundingClientRect().right > main.right + 1,
            )
            .map((element) => ({
              tag: element.tagName,
              className: element.className,
              label:
                element.getAttribute('aria-label') ||
                element.textContent?.trim().slice(0, 80),
              right: element.getBoundingClientRect().right,
              width: element.getBoundingClientRect().width,
            }))
            .slice(0, 30);
        }),
        null,
        2,
      ),
      contentType: 'application/json',
    });
    await expectDocumentContained(page);
    await expectMainContained(page);
    expect(
      fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
    ).toEqual([]);
    await restoreText?.();
  });
}

test('active filters stay visible when collapsed and disclosure never changes their query', async ({
  page,
  fixtureAPI,
}) => {
  const reads: URL[] = [];
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items/queue', ({ url }: APIRequest) => {
    reads.push(url);
    return { items: [], total: 0, matching_count: 0 };
  });
  await page.goto(
    '/action-items?tags=security&unassigned=true&due_within_hours=48',
  );
  const trigger = page.getByRole('button', { name: /^Filters\b/ });
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(trigger).toContainText('3');
  await expect(
    page.getByRole('textbox', { name: 'Tags', exact: true }),
  ).toHaveCount(0);
  const summary = page.getByLabel('Active filters', { exact: true });
  await expect(summary).toContainText('security');
  await expect(summary).toContainText('Unassigned only');
  await expect(summary).toContainText('48');
  await openAdvancedFilters(page);
  await expect(
    page.getByRole('textbox', { name: 'Tags', exact: true }),
  ).toHaveValue('security');
  await trigger.click();
  await expect(summary).toBeVisible();
  await openAdvancedFilters(page);
  await expect(
    page.getByRole('checkbox', { name: 'Unassigned only' }),
  ).toBeChecked();
  await expect(
    page.getByRole('spinbutton', { name: 'Hours', exact: true }),
  ).toHaveValue('48');
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toMatchObject({
    tags: 'security',
    unassigned: 'true',
    due_within_hours: '48',
  });
  expect(reads.length).toBeGreaterThan(0);
  expect(
    reads.every(
      (url) =>
        url.searchParams.get('tags') === 'security' &&
        url.searchParams.get('unassigned') === 'true' &&
        url.searchParams.get('due_within_hours') === '48',
    ),
  ).toBe(true);
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('root type requests preserve server pagination, complete Epics, and standalone membership', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  const singles = queuePage({
    items: Array.from({ length: 12 }, (_, index) =>
      actionItem(100 + index, { title: `Single task ${index + 1}` }),
    ),
    total: 12,
  }).items;
  const release = epicGroup(10, [actionItem(2), actionItem(3)]);
  const empty = epicGroup(11, []);
  empty.epic.title = 'Future work';
  const security = epicGroup(12, [actionItem(4)]);
  security.epic.title = 'Security';
  const roots: ActionItemGroupedPage['items'] = [
    singles[0],
    release,
    singles[1],
    empty,
    singles[2],
    security,
    ...singles.slice(3),
  ];
  roots.forEach((root, index) => {
    if (root.kind === 'epic') root.epic.position = index + 1;
    else root.position = index + 1;
  });
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items/queue', ({ url }: APIRequest) => {
    const kind = url.searchParams.get('kind') || 'all';
    const filtered = roots.filter(
      (root) => kind === 'all' || root.kind === kind,
    );
    const offset = Number(url.searchParams.get('offset') || 0);
    const limit = Number(url.searchParams.get('limit') || 10);
    return {
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
      matching_count: filtered.reduce(
        (count, root) =>
          count + (root.kind === 'item' ? 1 : root.matching_count),
        0,
      ),
    };
  });
  await page.goto('/action-items?offset=10&keep=1');
  await expect(
    page.getByText('Showing 11–15 of 15', { exact: true }),
  ).toBeVisible();
  const type = page.getByRole('combobox', { name: 'Item type', exact: true });
  await expect(type).toHaveValue('all');
  await type.selectOption('epic');
  await expect(
    page.getByText('Showing 1–3 of 3', { exact: true }),
  ).toBeVisible();
  const rootRows = page.locator(
    '.action-item-grouped-table > tbody > tr[data-rfd-draggable-id]',
  );
  await expect(rootRows).toHaveCount(3);
  expect(
    await rootRows.evaluateAll((rows) =>
      rows.map((row) => row.getAttribute('data-rfd-draggable-id')),
    ),
  ).toEqual(['epic:10', 'epic:11', 'epic:12']);
  await expect(
    page.getByRole('button', { name: 'Task 2', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Task 3', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Single task 1', exact: true }),
  ).toHaveCount(0);
  const releaseRegion = page.getByRole('region', {
    name: 'Epic Release',
    exact: true,
  });
  await releaseRegion
    .getByRole('button', { name: 'Release', exact: true })
    .click();
  await expect(releaseRegion).toHaveAttribute('data-expanded', 'false');
  await expectEpicFrame(releaseRegion);
  const emptyRegion = page.getByRole('region', {
    name: 'Epic Future work',
    exact: true,
  });
  await expect(
    emptyRegion.getByText('No matching action items in this Epic.'),
  ).toBeVisible();
  await expectEpicFrame(emptyRegion);
  await page.screenshot({
    path: testInfo.outputPath('collapsed-and-empty-epic-frames.png'),
    fullPage: true,
  });

  await type.selectOption('item');
  await expect(
    page.getByText('Showing 1–10 of 12', { exact: true }),
  ).toBeVisible();
  await expect(rootRows).toHaveCount(10);
  await expect(page.locator('.action-item-epic-group')).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Task 2', exact: true }),
  ).toHaveCount(0);
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(
    page.getByText('Showing 11–12 of 12', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Single task 12', exact: true }),
  ).toBeVisible();
  await type.selectOption('all');
  await expect(
    page.getByText('Showing 1–10 of 15', { exact: true }),
  ).toBeVisible();
  await type.selectOption('epic');
  await expect(rootRows).toHaveCount(3);
  await page.reload();
  await expect(type).toHaveValue('epic');
  await expect(
    page.getByText('Showing 1–3 of 3', { exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.get('keep')).toBe('1');
  const reads = fixtureAPI.requests
    .filter(
      (entry) => new URL(entry.url).pathname === '/api/action-items/queue',
    )
    .map((entry) => new URL(entry.url));
  expect(
    reads.some(
      (url) =>
        url.searchParams.get('kind') === 'item' &&
        url.searchParams.get('offset') === '10',
    ),
  ).toBe(true);
  expect(
    reads.some(
      (url) =>
        url.searchParams.get('kind') === 'epic' &&
        url.searchParams.get('offset') === '0',
    ),
  ).toBe(true);
  expect(reads.some((url) => !url.searchParams.has('kind'))).toBe(true);
  expect(reads.every((url) => url.searchParams.get('kind') !== 'all')).toBe(
    true,
  );
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
  await expectDocumentContained(page);
  await expectMainContained(page);
});
