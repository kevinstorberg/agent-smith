import { test, expect, type APIRequest } from './fixtures';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import type { Page } from '@playwright/test';
import { enlargeComputedText } from './typography';

function projectFixture(
  fixtureAPI: {
    get: (path: string, response: unknown) => void;
    mock: (
      method: 'PATCH',
      path: string,
      response: (request: APIRequest) => unknown,
      status?: number,
    ) => void;
  },
  initialProject: string | null = 'Source',
) {
  let item = actionItem(1, { project: initialProject, priority: 7 });
  const writes: unknown[] = [];
  fixtureAPI.get('/api/action-items/projects', {
    items: ['Source', 'Work', 'Other'].map((name, index) => ({
      id: index + 1,
      name,
      created_at: '2026-11-01T12:00:00Z',
    })),
    total: 3,
  });
  fixtureAPI.get('/api/action-items', ({ url }: APIRequest) => {
    const matches =
      (!url.searchParams.get('project') ||
        url.searchParams.get('project') === item.project) &&
      (!url.searchParams.has('unassigned') || item.project === null);
    return { items: matches ? [item] : [], total: matches ? 1 : 0 };
  });
  fixtureAPI.mock('PATCH', '/api/action-items/1', ({ request }: APIRequest) => {
    const body = request.postDataJSON();
    writes.push(body);
    item = { ...item, ...body, revision: item.revision + 1 };
    return item;
  });
  return writes;
}

async function liftPointer(page: Page) {
  const handle = page.getByRole('button', {
    name: /^(Reorder Task 1|Move Task 1 to project)$/,
  });
  await expect(handle).toBeEnabled();
  await handle.scrollIntoViewIfNeeded();
  const start = (await handle.boundingBox())!;
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    start.x + start.width / 2,
    start.y + start.height / 2 + 10,
    { steps: 3 },
  );
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toHaveAttribute('aria-disabled', 'true');
}

async function pointAtProject(page: Page, name: string) {
  const original = (await page.locator('.action-item-row').boundingBox())!;
  const tab = page.getByRole('tab', { name, exact: true });
  const box = (await tab.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, {
    steps: 12,
  });
  await expect(tab).toHaveClass(/project-drop-target/);
  await expect(page.locator('.action-item-project-drop-cue')).toHaveText(
    `→ ${name}`,
  );
  const row = (await page.locator('.action-item-row').boundingBox())!;
  expect(Math.abs(row.width - original.width)).toBeLessThanOrEqual(0.5);
  expect(Math.abs(row.height - original.height)).toBeLessThanOrEqual(0.5);
  const cue = (await page
    .locator('.action-item-project-drop-cue')
    .boundingBox())!;
  expect(cue.x).toBeGreaterThanOrEqual(0);
  expect(cue.x + cue.width).toBeLessThanOrEqual(page.viewportSize()!.width);
}

test('pointer drops on the exact middle folder without changing global priority', async ({
  page,
  fixtureAPI,
}) => {
  const writes = projectFixture(fixtureAPI);
  await page.goto('/action-items');
  await page
    .getByRole('tab', { name: 'Work', exact: true })
    .scrollIntoViewIfNeeded();
  await liftPointer(page);
  await pointAtProject(page, 'Work');
  await page.mouse.up();
  await expect
    .poll(() => writes)
    .toEqual([{ expected_revision: 1, project: 'Work' }]);
  await expect(page.getByLabel('Priority 7', { exact: true })).toBeVisible();
  await expect(
    page.getByRole('tab', { name: 'All projects', exact: true }),
  ).toHaveAttribute('aria-selected', 'true');
});

test('native release coordinates win on the SDK synchronous zero-offset drop path', async ({
  page,
  fixtureAPI,
}) => {
  const writes = projectFixture(fixtureAPI);
  await page.goto('/action-items');
  await page
    .getByRole('tab', { name: 'Work', exact: true })
    .scrollIntoViewIfNeeded();
  const handle = page.getByRole('button', {
    name: 'Reorder Task 1',
    exact: true,
  });
  await expect(handle).toBeEnabled();
  const original = (await handle.boundingBox())!;
  await liftPointer(page);
  await page.mouse.move(
    original.x + original.width / 2,
    original.y + original.height / 2,
  );
  const target = (await page
    .getByRole('tab', { name: 'Work', exact: true })
    .boundingBox())!;
  const client = await page.context().newCDPSession(page);
  await client.send('Input.dispatchMouseEvent', {
    type: 'mouseReleased',
    button: 'left',
    buttons: 0,
    clickCount: 1,
    x: target.x + target.width / 2,
    y: target.y + target.height / 2,
  });
  await expect
    .poll(() => writes)
    .toEqual([{ expected_revision: 1, project: 'Work' }]);
  await client.detach();
});

test('keyboard drag selects a named folder without changing the current view', async ({
  page,
  fixtureAPI,
}) => {
  const writes = projectFixture(fixtureAPI);
  await page.goto('/action-items');
  const handle = page.getByRole('button', {
    name: 'Reorder Task 1',
    exact: true,
  });
  await handle.focus();
  await page.keyboard.press('Space');
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toHaveAttribute('aria-disabled', 'true');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect(
    page.getByRole('status').filter({ hasText: 'Move Task 1 to Work' }),
  ).toBeVisible();
  await page.keyboard.press('Space');
  await expect
    .poll(() => writes)
    .toEqual([{ expected_revision: 1, project: 'Work' }]);
  await expect(
    page.getByRole('tab', { name: 'All projects', exact: true }),
  ).toHaveAttribute('aria-selected', 'true');
});

test('source-folder assignment refreshes membership and restores focus to the destination tab', async ({
  page,
  fixtureAPI,
}) => {
  const writes = projectFixture(fixtureAPI);
  await page.goto(
    '/action-items?project=Source&tags=security&due_within_hours=48',
  );
  const handle = page.getByRole('button', {
    name: 'Reorder Task 1',
    exact: true,
  });
  await handle.focus();
  await page.keyboard.press('Space');
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toHaveAttribute('aria-disabled', 'true');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Space');
  await expect.poll(() => writes.length).toBe(1);
  await expect(handle).toHaveCount(0);
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole('tab', { name: 'Source', exact: true }),
  ).toHaveAttribute('aria-selected', 'true');
  const reads = fixtureAPI.requests.filter(
    (entry) =>
      entry.method === 'GET' &&
      new URL(entry.url).pathname === '/api/action-items',
  );
  const latest = new URL(reads.at(-1)!.url);
  expect(latest.searchParams.get('project')).toBe('Source');
  expect(latest.searchParams.get('tags')).toBe('security');
  expect(latest.searchParams.get('due_within_hours')).toBe('48');
});

for (const cancel of ['outside', 'All projects', 'Escape', 'same project']) {
  test(`project hover makes no write after ${cancel}`, async ({
    page,
    fixtureAPI,
  }) => {
    const writes = projectFixture(fixtureAPI);
    await page.goto('/action-items');
    await page
      .getByRole('tab', { name: 'Work', exact: true })
      .scrollIntoViewIfNeeded();
    await liftPointer(page);
    await pointAtProject(page, 'Work');
    if (cancel === 'Escape') await page.keyboard.press('Escape');
    else {
      const target =
        cancel === 'outside'
          ? page.getByRole('heading', { name: 'Action items', exact: true })
          : page.getByRole('tab', {
              name: cancel === 'same project' ? 'Source' : 'All projects',
              exact: true,
            });
      const box = (await target.boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.up();
    }
    await expect(
      page.getByRole('tab', { name: 'All projects', exact: true }),
    ).not.toHaveAttribute('aria-disabled', 'true');
    expect(writes).toEqual([]);
    await expect(
      page.getByRole('tab', { name: 'All projects', exact: true }),
    ).toHaveAttribute('aria-selected', 'true');
  });
}

test('completed title-sorted items move by keyboard into an overflowing project tab', async ({
  page,
  fixtureAPI,
}) => {
  const writes = projectFixture(fixtureAPI);
  await page.goto('/action-items?status=completed&sort=title');
  const handle = page.getByRole('button', {
    name: 'Move Task 1 to project',
    exact: true,
  });
  await handle.focus();
  await page.keyboard.press('Space');
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toHaveAttribute('aria-disabled', 'true');
  await page.keyboard.press('ArrowLeft');
  await expect(
    page.getByRole('tab', { name: 'Other', exact: true }),
  ).toHaveClass(/project-drop-target/);
  await page.keyboard.press('Space');
  await expect
    .poll(() => writes)
    .toEqual([{ expected_revision: 1, project: 'Other' }]);
});

test('real touch long-press uses the released finger position for project assignment', async ({
  page,
  fixtureAPI,
}) => {
  const writes = projectFixture(fixtureAPI);
  await page.goto('/action-items');
  await page
    .getByRole('tab', { name: 'Work', exact: true })
    .scrollIntoViewIfNeeded();
  const handle = page.getByRole('button', {
    name: 'Reorder Task 1',
    exact: true,
  });
  await expect(handle).toBeEnabled();
  const box = (await handle.boundingBox())!;
  const client = await page.context().newCDPSession(page);
  await client.send('Input.dispatchTouchEvent', {
    type: 'touchStart',
    touchPoints: [{ x: box.x + box.width / 2, y: box.y + box.height / 2 }],
  });
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toHaveAttribute('aria-disabled', 'true');
  const target = (await page
    .getByRole('tab', { name: 'Work', exact: true })
    .boundingBox())!;
  await client.send('Input.dispatchTouchEvent', {
    type: 'touchMove',
    touchPoints: [
      { x: target.x + target.width / 2, y: target.y + target.height / 2 },
    ],
  });
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toHaveClass(/project-drop-target/);
  await client.send('Input.dispatchTouchEvent', {
    type: 'touchEnd',
    touchPoints: [],
  });
  await expect
    .poll(() => writes)
    .toEqual([{ expected_revision: 1, project: 'Work' }]);
  await client.detach();
});

test('conflicted project drops refresh the displayed revision and require a new gesture', async ({
  page,
  fixtureAPI,
}) => {
  projectFixture(fixtureAPI);
  const writes: unknown[] = [];
  fixtureAPI.mock(
    'PATCH',
    '/api/action-items/1',
    ({ request }: APIRequest) => {
      writes.push(request.postDataJSON());
      fixtureAPI.get('/api/action-items', {
        items: [actionItem(1, { project: 'Source', revision: 2 })],
        total: 1,
      });
      return { detail: 'Source changed. Reread before retrying.' };
    },
    409,
  );
  await page.goto('/action-items');
  await page
    .getByRole('tab', { name: 'Work', exact: true })
    .scrollIntoViewIfNeeded();
  await liftPointer(page);
  await pointAtProject(page, 'Work');
  await page.mouse.up();
  await expect(page.getByRole('alert')).toContainText('Source changed');
  await expect(
    page.getByRole('tab', { name: 'All projects', exact: true }),
  ).not.toHaveAttribute('aria-disabled', 'true');
  expect(writes).toEqual([{ expected_revision: 1, project: 'Work' }]);
  fixtureAPI.mock('PATCH', '/api/action-items/1', ({ request }: APIRequest) => {
    writes.push(request.postDataJSON());
    return actionItem(1, { project: 'Work', revision: 3 });
  });
  await liftPointer(page);
  await pointAtProject(page, 'Work');
  await page.mouse.up();
  await expect
    .poll(() => writes)
    .toEqual([
      { expected_revision: 1, project: 'Work' },
      { expected_revision: 2, project: 'Work' },
    ]);
});

test('list and catalog polling remain paused throughout a keyboard project choice', async ({
  page,
  fixtureAPI,
}) => {
  const writes = projectFixture(fixtureAPI);
  await page.goto('/action-items');
  await page.getByRole('tab', { name: 'Work', exact: true }).waitFor();
  const handle = page.getByRole('button', {
    name: 'Reorder Task 1',
    exact: true,
  });
  await expect(handle).toBeEnabled();
  await page.clock.install();
  await handle.focus();
  await page.keyboard.press('Space');
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toHaveAttribute('aria-disabled', 'true');
  const before = fixtureAPI.requests.filter(
    (entry) =>
      entry.method === 'GET' &&
      new URL(entry.url).pathname.startsWith('/api/action-items'),
  ).length;
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await page.clock.fastForward(30_000);
  expect(
    fixtureAPI.requests.filter(
      (entry) =>
        entry.method === 'GET' &&
        new URL(entry.url).pathname.startsWith('/api/action-items'),
    ),
  ).toHaveLength(before);
  await page.keyboard.press('Space');
  await expect.poll(() => writes.length).toBe(1);
});

test('keyboard project choice reaches the fiftieth folder without cancelling the drag', async ({
  page,
  fixtureAPI,
}) => {
  const writes = projectFixture(fixtureAPI);
  const names = [
    'Source',
    ...Array.from({ length: 49 }, (_, index) => `Project ${index + 1}`),
  ];
  fixtureAPI.get('/api/action-items/projects', {
    items: names.map((name, index) => ({
      id: index + 1,
      name,
      created_at: '2026-11-01T00:00:00Z',
    })),
    total: 50,
  });
  await page.goto('/action-items?project=Source');
  const handle = page.getByRole('button', {
    name: 'Reorder Task 1',
    exact: true,
  });
  await handle.focus();
  await page.keyboard.press('Space');
  await expect(
    page.getByRole('tab', { name: 'Source', exact: true }),
  ).toHaveAttribute('aria-disabled', 'true');
  await page.keyboard.press('ArrowLeft');
  const target = page.getByRole('tab', { name: 'Project 49', exact: true });
  await expect(target).toHaveClass(/project-drop-target/);
  await expect(target).toBeInViewport({ ratio: 0.99 });
  await page.keyboard.press('Space');
  await expect
    .poll(() => writes)
    .toEqual([{ expected_revision: 1, project: 'Project 49' }]);
  await expect(target).toBeFocused();
  await expect(
    page.getByRole('tab', { name: 'Source', exact: true }),
  ).toHaveAttribute('aria-selected', 'true');
});

test('unassigned-only items move to a project without changing the current filter', async ({
  page,
  fixtureAPI,
}) => {
  const writes = projectFixture(fixtureAPI, null);
  await page.goto('/action-items?unassigned=true');
  const handle = page.getByRole('button', {
    name: 'Reorder Task 1',
    exact: true,
  });
  await handle.focus();
  await page.keyboard.press('Space');
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toHaveAttribute('aria-disabled', 'true');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Space');
  await expect.poll(() => writes.length).toBe(1);
  await expect(handle).toHaveCount(0);
  await expect(
    page.getByRole('checkbox', { name: 'Unassigned only' }),
  ).toBeChecked();
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toBeFocused();
});

test('project pointer targeting remains usable at doubled text size', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  const writes = projectFixture(fixtureAPI);
  await page.goto('/action-items');
  const handle = page.getByRole('button', {
    name: 'Reorder Task 1',
    exact: true,
  });
  await expect(handle).toBeEnabled();
  await page.getByRole('tab', { name: 'Work', exact: true }).waitFor();
  const rowCell = page.locator('.action-item-row > td').first();
  const initialFont = await rowCell.evaluate((cell) =>
    parseFloat(getComputedStyle(cell).fontSize),
  );
  await enlargeComputedText(page, 2, { preserveMotion: true });
  const enlargedFont = await rowCell.evaluate((cell) =>
    parseFloat(getComputedStyle(cell).fontSize),
  );
  expect(enlargedFont).toBeCloseTo(initialFont * 2, 1);
  await page
    .getByRole('tab', { name: 'Work', exact: true })
    .scrollIntoViewIfNeeded();
  await liftPointer(page);
  await pointAtProject(page, 'Work');
  const cueFont = await page
    .locator('.action-item-project-drop-cue')
    .evaluate((cue) => parseFloat(getComputedStyle(cue).fontSize));
  expect(cueFont).toBeCloseTo(enlargedFont, 1);
  await testInfo.attach('drag-font-sizes.json', {
    body: JSON.stringify({ initialFont, enlargedFont, cueFont }),
    contentType: 'application/json',
  });
  if (['chromium-1440', 'chromium-320'].includes(testInfo.project.name)) {
    const screenshotPath = testInfo.outputPath('project-drag-2x.png');
    await page.screenshot({
      path: screenshotPath,
      fullPage: false,
    });
    await testInfo.attach('project-drag-2x', {
      path: screenshotPath,
      contentType: 'image/png',
    });
  }
  await page.mouse.up();
  await expect
    .poll(() => writes)
    .toEqual([{ expected_revision: 1, project: 'Work' }]);
});

test('repeated pointer project choices and tab scrolling keep the cue contained without navigating', async ({
  page,
  fixtureAPI,
}) => {
  const writes = projectFixture(fixtureAPI);
  await page.goto('/action-items');
  await page
    .getByRole('tab', { name: 'Work', exact: true })
    .scrollIntoViewIfNeeded();
  await liftPointer(page);
  for (const name of ['Work', 'Source', 'Other', 'Work']) {
    await page
      .getByRole('tab', { name, exact: true })
      .evaluate((button) =>
        button.scrollIntoView({ block: 'nearest', inline: 'nearest' }),
      );
    await pointAtProject(page, name);
    await expect(
      page.getByRole('tab', { name: 'All projects', exact: true }),
    ).toHaveAttribute('aria-selected', 'true');
    expect(writes).toEqual([]);
  }
  await page.mouse.up();
  await expect
    .poll(() => writes)
    .toEqual([{ expected_revision: 1, project: 'Work' }]);
});
