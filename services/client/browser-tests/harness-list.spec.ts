import { test, expect, type APIRequest } from './fixtures';
import { harnessFixture } from './harnessFixture';
import {
  expectControlContained,
  expectControlsUnclipped,
  expectDocumentContained,
  expectMainContained,
} from './geometry';

const labels = {
  agent: 'Agents',
  hook: 'Hooks',
  rule: 'Rules',
  skill: 'Skills',
  tool: 'Tools',
};

for (const [kind, label] of Object.entries(labels)) {
  test(`${label} keep metadata and toggle controls reachable in their scroll region`, async ({
    page,
    fixtureAPI,
  }) => {
    let item = harnessFixture({
      name: 'release_review_with_context',
      project: 'a_long_project_name_for_the_release_review',
      agents: ['claude', 'codex', 'gemini'],
      clone_as_skill: false,
      version: 2,
      configs: [
        {
          id: 1,
          device: 'laptop',
          repo: '/Users/example/release-project',
          agents: ['claude'],
          subagents: [],
          enabled: true,
          exclude: false,
        },
      ],
    });
    const path = `/api/harness/items/${kind}`;
    fixtureAPI.get(path, () => ({ items: [item], total: 1 }));
    fixtureAPI.mock('PATCH', `${path}/1`, ({ request }: APIRequest) => {
      const update = request.postDataJSON();
      expect(update).toEqual(
        kind === 'rule' ? { clone_as_skill: true } : { enabled: false },
      );
      item = { ...item, ...update };
      return item;
    });
    await page.goto(`/harness/${label.toLowerCase()}`);
    const region = page.getByRole('region', {
      name: `${label} list`,
      exact: true,
    });
    await expect(region.getByText(item.name, { exact: true })).toBeVisible();
    await expect(region).toHaveAttribute('tabindex', '0');
    await region.focus();
    const scrollable = await region.evaluate(
      (element) => element.scrollWidth > element.clientWidth,
    );
    if (scrollable) {
      await page.keyboard.press('ArrowRight');
      await expect
        .poll(() => region.evaluate((element) => element.scrollLeft))
        .toBeGreaterThan(0);
    }
    const version = region.getByText('v2', { exact: true });
    await version.scrollIntoViewIfNeeded();
    await expectControlContained(version, region);
    const toggle = region.getByRole('checkbox', {
      name:
        kind === 'rule'
          ? `Clone ${item.name} as a skill`
          : `Enable ${item.name}`,
      exact: true,
    });
    await toggle.click();
    await expect
      .poll(
        () =>
          fixtureAPI.requests.filter((entry) => entry.method === 'PATCH')
            .length,
      )
      .toBe(1);
    await expect(toggle).toBeChecked({ checked: kind === 'rule' });
    const fonts = await region
      .locator('.tag')
      .evaluateAll((elements) =>
        elements.map((element) =>
          parseFloat(getComputedStyle(element).fontSize),
        ),
      );
    expect(Math.min(...fonts)).toBeGreaterThanOrEqual(12);
    await expectDocumentContained(page);
    await expectMainContained(page);
    await expectControlsUnclipped(page);
  });
}

test('Rules keyboard drag preserves columns and scroll position, then reconciles the saved order', async ({
  page,
  fixtureAPI,
}) => {
  let items = [1, 2, 3].map((id) =>
    harnessFixture({ id, name: `release_review_${id}`, sort_key: id }),
  );
  fixtureAPI.get('/api/harness/items/rule', () => ({
    items,
    total: items.length,
  }));
  fixtureAPI.mock(
    'POST',
    '/api/harness/items/rule/1/move',
    ({ request }: APIRequest) => {
      expect(request.postDataJSON()).toEqual({
        before_id: 3,
        expected_updated_at: items[0].updated_at,
        expected_anchor_updated_at: items[2].updated_at,
      });
      items = [items[1], items[0], items[2]];
      return { id: 1, sort_key: 2, updated_at: items[1].updated_at };
    },
  );
  await page.goto('/harness/rules');
  const region = page.getByRole('region', { name: 'Rules list', exact: true });
  const rows = region.locator('.harness-list-row');
  await expect(rows).toHaveCount(3);
  const handle = rows.first().locator('[data-rfd-drag-handle-draggable-id]');
  await handle.focus();
  const before = await region.evaluate((element) => ({
    scrollLeft: element.scrollLeft,
    columns: [...element.querySelectorAll('.harness-list-header > div')].map(
      (cell) => cell.getBoundingClientRect().width,
    ),
  }));
  await page.keyboard.press('Space');
  await expect(rows.first()).toHaveCSS('position', 'fixed');
  const during = await region
    .locator('.harness-list-header > div')
    .evaluateAll((cells) =>
      cells.map((cell) => cell.getBoundingClientRect().width),
    );
  expect(during).toEqual(before.columns);
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Space');
  await expect
    .poll(
      () =>
        fixtureAPI.requests.filter((entry) => entry.method === 'POST').length,
    )
    .toBe(1);
  await expect(rows.locator(':scope > div:nth-child(2)')).toHaveText([
    'release_review_2',
    'release_review_1',
    'release_review_3',
  ]);
  expect(await region.evaluate((element) => element.scrollLeft)).toBe(
    before.scrollLeft,
  );
  await page.reload();
  await expect(
    region.locator('.harness-list-row > div:nth-child(2)'),
  ).toHaveText(['release_review_2', 'release_review_1', 'release_review_3']);
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('Rules filter fields share one baseline and recover from an error into a visible empty state', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get(
    '/api/harness/items/rule',
    { detail: 'Synthetic unavailable response' },
    503,
  );
  await page.goto('/harness/rules');
  await expect(page.getByRole('alert')).toContainText('Could not load rules');
  const search = page.getByRole('textbox', { name: 'Search', exact: true });
  const project = page.getByRole('textbox', {
    name: 'Project scope',
    exact: true,
  });
  await expect(
    page.getByRole('combobox', { name: 'Sort', exact: true }),
  ).toHaveCount(0);
  await expect(search).toBeVisible();
  const searchBounds = await search.boundingBox();
  const sortBounds = await project.boundingBox();
  if (page.viewportSize()!.width >= 1024)
    expect(Math.abs(searchBounds!.y - sortBounds!.y)).toBeLessThanOrEqual(1);
  fixtureAPI.get('/api/harness/items/rule', { items: [], total: 0 });
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  const empty = page.getByText('No rules found', { exact: true });
  await expectControlContained(empty, page.locator('#main-content'));
  await expectDocumentContained(page);
  await expectMainContained(page);
});
