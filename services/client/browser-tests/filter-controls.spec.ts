import type { Locator, Page } from '@playwright/test';
import { TYPE_PATHS } from '../src/constants';
import { profileFixture } from '../src/pages/__tests__/profileFixture';
import { test, expect } from './fixtures';
import {
  expectControlReachable,
  expectControlsUnclipped,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { enlargeComputedText } from './typography';

const views = [
  ...Object.values(TYPE_PATHS).map((plural) => ({
    path: `/harness/${plural}`,
    query: 'Search',
  })),
  { path: '/action-items', query: 'Search action items' },
  { path: '/profiles', query: 'Search profiles' },
  { path: '/memory', query: 'Search memories' },
  { path: '/meetings', query: 'Search meetings' },
  { path: '/meetings?tab=vocabulary', query: 'Search vocabulary' },
  { path: '/plans', query: 'Search plans' },
  { path: '/chat', query: 'Search rooms' },
  { path: '/jobs', query: 'Search' },
  { path: '/audit', query: 'Search' },
  { path: '/proposals', query: 'Search' },
  { path: '/eval-configs', query: 'Search' },
  { path: '/evals', query: 'Search' },
];

test.beforeEach(async ({ fixtureAPI }) => {
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  for (const path of [
    ...Object.keys(TYPE_PATHS).map((type) => `/api/harness/items/${type}`),
    '/api/action-items',
    '/api/profiles',
    '/api/jobs/graph/persona',
    '/api/memory/list',
    '/api/memory/search',
    '/api/meetings',
    '/api/meetings/vocabulary',
    '/api/plans',
    '/api/chat',
    '/api/jobs',
    '/api/audit/events',
    '/api/proposals',
    '/api/eval-configs/suites',
    '/api/evals',
  ])
    fixtureAPI.get(path, { items: [], total: 0 });
  fixtureAPI.get('/api/chat/config', { participants: [] });
  fixtureAPI.get('/api/audit/counts', { claude: 0, codex: 0, gemini: 0 });
  fixtureAPI.get('/api/proposals/counts', {
    pending: 0,
    approved: 0,
    rejected: 0,
  });
  for (const path of [
    '/api/evals/categories',
    '/api/evals/subcategories',
    '/api/evals/chart/average',
  ])
    fixtureAPI.get(path, []);
  fixtureAPI.get('/api/evals/facets', { scenarios: [], models: [] });
});

async function expectFilterRows(page: Page, checkPage = true) {
  const main = (await page.locator('#main-content').boundingBox())!;
  for (const row of await page
    .locator(
      '.resource-controls:visible, .profile-filters:visible, .memory-controls:visible',
    )
    .all()) {
    const controls = await row
      .locator('input, select, button')
      .evaluateAll((elements) =>
        elements.map((element) => {
          const visual =
            element instanceof HTMLInputElement && element.type === 'checkbox'
              ? element.closest('label')!
              : element;
          const box = visual.getBoundingClientRect();
          return {
            name:
              element.getAttribute('aria-label') ||
              (element as HTMLInputElement).labels?.[0]?.textContent?.trim() ||
              element.textContent?.trim(),
            x: box.x,
            right: box.right,
            y: box.y,
            bottom: box.bottom,
            width: box.width,
            height: box.height,
          };
        }),
      );
    for (const control of controls) {
      expect(
        control.x,
        `${control.name} must fit the visible main area`,
      ).toBeGreaterThanOrEqual(main.x - 1);
      expect(
        control.right,
        `${control.name} must fit the visible main area`,
      ).toBeLessThanOrEqual(main.x + main.width + 1);
    }
    for (let i = 0; i < controls.length; i++)
      for (const next of controls.slice(i + 1)) {
        const current = controls[i];
        const horizontal =
          Math.min(current.right, next.right) - Math.max(current.x, next.x);
        const vertical =
          Math.min(current.bottom, next.bottom) - Math.max(current.y, next.y);
        expect(
          horizontal > 1 && vertical > 1,
          `${current.name} overlaps ${next.name}`,
        ).toBe(false);
        if (vertical >= Math.min(current.height, next.height) / 2) {
          expect(
            Math.abs(current.bottom - next.bottom),
            `${current.name} and ${next.name} must align on their shared row`,
          ).toBeLessThanOrEqual(2);
        }
      }
    const values = await row.getByRole('combobox').evaluateAll((elements) =>
      elements.map((element) => {
        const select = element as HTMLSelectElement;
        const style = getComputedStyle(select);
        const context = document.createElement('canvas').getContext('2d')!;
        context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
        return {
          name: select.labels?.[0]?.textContent?.trim(),
          text: context.measureText(select.selectedOptions[0].text).width,
          available:
            select.clientWidth -
            parseFloat(style.paddingLeft) -
            parseFloat(style.paddingRight),
        };
      }),
    );
    for (const value of values)
      expect(
        value.text,
        `${value.name} must show its selected text`,
      ).toBeLessThanOrEqual(value.available + 1);
  }
  await expectDocumentContained(page);
  if (checkPage) await expectMainContained(page);
  await expectControlsUnclipped(page);
}

for (const enlarged of [false, true])
  for (const view of views) {
    test(`${view.path} keeps filters aligned without Reset view${enlarged ? ' at 200% text' : ''}`, async ({
      page,
    }, testInfo) => {
      await page.goto(view.path);
      await expect(page.getByLabel(view.query, { exact: true })).toBeVisible();
      if (enlarged) await enlargeComputedText(page);
      await expect(
        page.getByRole('button', {
          name: 'Reset view',
          exact: true,
          includeHidden: true,
        }),
      ).toHaveCount(0);
      // The independent status-selection change covers the enlarged Action item tab strip.
      await expectFilterRows(
        page,
        !(
          enlarged &&
          view.path === '/action-items' &&
          page.viewportSize()!.width === 320
        ),
      );
      await testInfo.attach('filter-controls.png', {
        body: await page.screenshot({ fullPage: true }),
        contentType: 'image/png',
      });
    });
  }

for (const view of [
  { path: '/memory', select: 'Sort' },
  { path: '/memory?q=release', select: 'Sort' },
  { path: '/jobs', select: 'Scheduling' },
  { path: '/action-items?status=completed', select: 'Sort' },
]) {
  test(`${view.path} shows every selected ${view.select} option at200% text`, async ({
    page,
  }) => {
    await page.goto(view.path);
    const select = page.getByRole('combobox', {
      name: view.select,
      exact: true,
    });
    await expect(select).toBeVisible();
    await enlargeComputedText(page);
    const values = await select
      .locator('option')
      .evaluateAll((options) =>
        options.map((option) => (option as HTMLOptionElement).value),
      );
    for (const value of values) {
      await select.selectOption(value);
      await expect(select).toHaveValue(value);
      await expectFilterRows(
        page,
        !(
          view.path.startsWith('/action-items') &&
          page.viewportSize()!.width === 320
        ),
      );
    }
  });
}

test('Memory puts the shared boxed checkbox after Sort in both visual and keyboard order', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  await page.goto('/memory?q=release&searchSort=created_at_asc');
  const checkbox = page.getByRole('checkbox', { name: 'Meetings only' });
  const row = page.locator('.memory-controls').filter({ has: checkbox });
  const sort = page.getByRole('combobox', { name: 'Sort', exact: true });
  await expect(sort).toHaveValue('created_at_asc');
  const order = await row.locator('input, select').evaluateAll((elements) =>
    elements.map((element) => {
      const label = (element as HTMLInputElement).labels?.[0];
      return (
        label?.querySelector('.form-label') || label
      )?.textContent?.trim();
    }),
  );
  expect(order).toEqual(['Repository', 'Tags', 'Sort', 'Meetings only']);
  const checkboxBox = await checkbox.boundingBox();
  expect(checkboxBox!.width).toBe(18);
  expect(checkboxBox!.height).toBe(18);
  const label = checkbox.locator('..');
  const checkboxGeometry = async () => {
    const [box, selectBox] = await Promise.all([
      label.boundingBox(),
      sort.boundingBox(),
    ]);
    const text = await label.evaluate((element) => {
      const node = [...element.childNodes].find(
        (node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim(),
      )!;
      const range = document.createRange();
      range.selectNode(node);
      const bounds = range.getBoundingClientRect();
      return {
        center: bounds.y + bounds.height / 2,
        lineHeight: getComputedStyle(element).lineHeight,
      };
    });
    expect(
      Math.abs(box!.height - selectBox!.height),
      'The boxed checkbox stays close to native control height',
    ).toBeLessThanOrEqual(3);
    expect(
      Math.abs(text.center - box!.y - box!.height / 2),
      'Checkbox text stays vertically centered',
    ).toBeLessThanOrEqual(1);
    return { box, selectBox, text };
  };
  await expect(label).toHaveClass(/filter-checkbox/);
  expect((await label.boundingBox())!.height).toBeGreaterThanOrEqual(40);
  const normalGeometry = await checkboxGeometry();
  if (page.viewportSize()!.width >= 1024) {
    const [selectBox, labelBox] = await Promise.all([
      sort.boundingBox(),
      label.boundingBox(),
    ]);
    expect(labelBox!.x).toBeGreaterThan(selectBox!.x + selectBox!.width);
    expect(
      Math.abs(
        labelBox!.y + labelBox!.height - selectBox!.y - selectBox!.height,
      ),
    ).toBeLessThanOrEqual(2);
  }
  await sort.focus();
  await page.keyboard.press('Tab');
  await expect(checkbox).toBeFocused();
  await page.keyboard.press('Space');
  await expect(checkbox).toBeChecked();
  await expect(checkbox).toHaveCSS('outline-style', 'solid');
  await expect
    .poll(() =>
      fixtureAPI.requests.some((entry) => {
        const url = new URL(entry.url);
        return (
          url.pathname === '/api/memory/search' &&
          url.searchParams.get('meeting_only') === 'true' &&
          url.searchParams.get('sort') === 'created_at_asc'
        );
      }),
    )
    .toBe(true);
  await label.click();
  await expect(checkbox).not.toBeChecked();
  const clear = page.getByRole('button', { name: 'Clear', exact: true });
  await expectControlReachable(clear);
  await clear.click();
  await expect(
    page.getByRole('textbox', { name: 'Search memories' }),
  ).toHaveValue('');
  await expectFilterRows(page);
  await enlargeComputedText(page);
  const enlargedGeometry = await checkboxGeometry();
  if (page.viewportSize()!.width === 1440) {
    const [selectBox, labelBox] = await Promise.all([
      sort.boundingBox(),
      label.boundingBox(),
    ]);
    expect(labelBox!.x).toBeGreaterThan(selectBox!.x + selectBox!.width);
    await expectSameRow(sort, label);
  }
  await expectFilterRows(page);
  await testInfo.attach('boxed-checkbox-geometry.json', {
    body: JSON.stringify({ normalGeometry, enlargedGeometry }),
    contentType: 'application/json',
  });
  await testInfo.attach('memory-boxed-checkbox.png', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });
});

async function expectSameRow(first: Locator, second: Locator) {
  const [a, b] = await Promise.all([first.boundingBox(), second.boundingBox()]);
  expect(
    Math.abs(a!.y + a!.height - b!.y - b!.height),
    'Status filters must share the control row when space permits',
  ).toBeLessThanOrEqual(2);
}

for (const view of [
  {
    path: '/plans',
    label: 'Plan status',
    sort: null,
    status: 'draft',
    api: '/api/plans',
  },
  {
    path: '/proposals',
    label: 'Proposal status',
    sort: 'Sort proposals',
    status: 'approved',
    api: '/api/proposals',
  },
]) {
  test(`${view.path} keeps status buttons in the filter flow and exposes the pressed state`, async ({
    page,
    fixtureAPI,
  }) => {
    await page.goto(view.path);
    const status = page.getByRole('group', { name: view.label });
    const button = status.getByRole('button', {
      name: new RegExp(`^${view.status}(?: \\(\\d+\\))?$`),
    });
    if (page.viewportSize()!.width === 1440)
      await expectSameRow(
        view.sort
          ? page.getByRole('combobox', { name: view.sort })
          : page.getByRole('textbox', { name: 'Project scope' }),
        button,
      );
    await button.focus();
    await button.press('Space');
    await expect(button).toHaveAttribute('aria-pressed', 'true');
    await expect(status.getByRole('button', { pressed: true })).toHaveCount(1);
    await expect
      .poll(() =>
        fixtureAPI.requests.some((entry) => {
          const url = new URL(entry.url);
          return (
            url.pathname === view.api &&
            url.searchParams.get('status') === view.status
          );
        }),
      )
      .toBe(true);
    await expectFilterRows(page);
    await enlargeComputedText(page);
    await expectFilterRows(page);
    await expectControlReachable(button);
  });
}

test('Analysis transcript search checkbox wraps inside the dialog without changing its separate row', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get(`/api/profiles/${profileFixture.id}`, profileFixture);
  fixtureAPI.get('/api/meeting-analysis/candidates', {
    items: [],
    total: 0,
    profile: {
      id: profileFixture.id,
      revision: profileFixture.revision,
      display_name: profileFixture.display_name,
    },
  });
  await page.goto(`/profiles/${profileFixture.id}`);
  await page
    .getByRole('button', { name: 'Review past meetings', exact: true })
    .click();
  const checkbox = page.getByRole('checkbox', {
    name: 'Include saved transcript text in search',
  });
  await expect(checkbox).toBeVisible();
  await enlargeComputedText(page);
  const label = checkbox.locator('..');
  const dialog = page.getByRole('dialog');
  const [bounds, parent] = await Promise.all([
    label.boundingBox(),
    dialog.boundingBox(),
  ]);
  expect(bounds!.x).toBeGreaterThanOrEqual(parent!.x);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(
    parent!.x + parent!.width,
  );
  await expectControlReachable(checkbox);
  await checkbox.focus();
  await checkbox.press('Space');
  await expect(checkbox).toBeChecked();
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
});

test('Discussion topics reuse readable status-specific sort choices at200% text', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get(`/api/profiles/${profileFixture.id}`, profileFixture);
  fixtureAPI.get(`/api/profiles/${profileFixture.id}/discussion-topics`, {
    profile_id: profileFixture.id,
    items: [],
    total: 0,
  });
  await page.goto(`/profiles/${profileFixture.id}?tab=topics`);
  const section = page.getByRole('region', {
    name: 'Discussion topics',
    exact: true,
  });
  const select = section.getByRole('combobox', { name: 'Sort', exact: true });
  await expect(select).toBeVisible();
  await enlargeComputedText(page);
  for (const status of ['Open', 'Completed', 'All']) {
    await section.getByRole('tab', { name: status, exact: true }).click();
    const values = await select
      .locator('option')
      .evaluateAll((options) =>
        options.map((option) => (option as HTMLOptionElement).value),
      );
    for (const value of values) {
      await select.selectOption(value);
      await expect(select).toHaveValue(value);
      await expectFilterRows(page, page.viewportSize()!.width !== 320);
    }
  }
});
