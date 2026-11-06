import { test, expect, type APIRequest } from './fixtures';
import { harnessFixture } from './harnessFixture';
import { enlargeComputedText } from './typography';
import { expectControlReachable, expectDocumentContained } from './geometry';

const kinds = {
  rule: 'Rules',
  skill: 'Skills',
  tool: 'Tools',
  hook: 'Hooks',
  agent: 'Agents',
};
const pairs = [
  ['Order', 'manual', 'manual_desc'],
  ['Name', 'name', 'name_desc'],
  ['Project', 'project_asc', 'project_desc'],
  ['Enabled', 'enabled_asc', 'enabled_desc'],
  ['Skill Clone', 'clone_as_skill_asc', 'clone_as_skill_desc'],
  ['Agents', 'agents_asc', 'agents_desc'],
  ['Configs', 'config_count_asc', 'config_count_desc'],
  ['Version', 'version_asc', 'version_desc'],
  ['Updated', 'updated_asc', 'updated'],
] as const;

for (const [kind, label] of Object.entries(kinds)) {
  test(`${label} use valid table roles and toggle all data headers with persistent read-only sorting`, async ({
    page,
    fixtureAPI,
  }) => {
    fixtureAPI.get(`/api/harness/items/${kind}`, {
      items: [harnessFixture({ name: 'Metadata fixture' })],
      total: 1,
    });
    await page.goto(`/harness/${label.toLowerCase()}?sort=newest`);
    await expect(
      page.getByText('Metadata fixture', { exact: true }),
    ).toBeVisible();
    const table = page.getByRole('table');
    const columns = pairs.filter(
      ([name]) => name !== 'Skill Clone' || kind === 'rule',
    );
    await expect(table.getByRole('columnheader')).toHaveCount(columns.length);
    await expect(table.getByRole('rowgroup')).toHaveCount(2);
    await expect(page.getByRole('grid')).toHaveCount(0);
    await expect(
      page.getByRole('combobox', { name: 'Sort', exact: true }),
    ).toHaveCount(0);
    await expect(
      table.locator('.harness-list-row').getByRole('cell'),
    ).toHaveCount(columns.length);
    for (const [name, ascending, descending] of columns) {
      const header = table.getByRole('columnheader', { name, exact: true });
      const first = name === 'Updated' ? descending : ascending;
      const second = name === 'Updated' ? ascending : descending;
      for (const sort of [first, second]) {
        await header.getByRole('button').click();
        await expect
          .poll(() => new URL(page.url()).searchParams.get('sort'))
          .toBe(sort);
        await expect(header).toHaveAttribute(
          'aria-sort',
          sort === ascending ? 'ascending' : 'descending',
        );
      }
    }
    await page.reload();
    await expect(
      table.getByRole('columnheader', { name: 'Updated', exact: true }),
    ).toHaveAttribute('aria-sort', 'ascending');
    expect(
      fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
    ).toEqual([]);
  });
}

test('Harness Name sorting resets a committed page and survives stale completions with native keyboard focus', async ({
  page,
  fixtureAPI,
}) => {
  let finishAsc!: (value: unknown) => void;
  let finishDesc!: (value: unknown) => void;
  const ascending = new Promise((resolve) => {
    finishAsc = resolve;
  });
  const descending = new Promise((resolve) => {
    finishDesc = resolve;
  });
  fixtureAPI.get('/api/harness/items/rule', ({ url }: APIRequest) => {
    const sort = url.searchParams.get('sort');
    if (sort === 'name') return ascending;
    if (sort === 'name_desc') return descending;
    return {
      items: [
        harnessFixture({
          name:
            url.searchParams.get('offset') === '10'
              ? 'Committed second page'
              : 'Initial page',
        }),
      ],
      total: 25,
    };
  });
  await page.goto('/harness/rules?project=work&keep=1');
  await expect(page.getByText('Initial page', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(
    page.getByText('Committed second page', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Showing 11–20 of 25', { exact: true }),
  ).toBeVisible();
  const name = page.getByRole('columnheader', { name: 'Name', exact: true });
  const button = name.getByRole('button');
  await page
    .getByRole('textbox', { name: 'Project scope', exact: true })
    .focus();
  for (
    let count = 0;
    count < 12 &&
    !(await button.evaluate((node) => node === document.activeElement));
    count++
  )
    await page.keyboard.press('Tab');
  await expect(button).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('table')).toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('[aria-sort]')).toHaveCount(0);
  await expect(button).toBeFocused();
  await page.keyboard.press('Space');
  await expect
    .poll(
      () =>
        fixtureAPI.requests.filter(
          (entry) =>
            new URL(entry.url).searchParams.get('sort') === 'name_desc',
        ).length,
    )
    .toBe(1);
  finishDesc({
    items: [harnessFixture({ name: 'Global descending result' })],
    total: 40,
  });
  await expect(
    page.getByText('Global descending result', { exact: true }),
  ).toBeVisible();
  await expect(name).toHaveAttribute('aria-sort', 'descending');
  const late = page.waitForResponse(
    (response) => new URL(response.url()).searchParams.get('sort') === 'name',
  );
  finishAsc({
    items: [harnessFixture({ name: 'Stale ascending result' })],
    total: 99,
  });
  await (await late).finished();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  await expect(
    page.getByText('Stale ascending result', { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText('Showing 1–10 of 40', { exact: true }),
  ).toBeVisible();
  await expect(button).toBeFocused();
  const query = new URL(page.url()).searchParams;
  expect(Object.fromEntries(query)).toMatchObject({
    project: 'work',
    keep: '1',
    sort: 'name_desc',
    offset: '0',
  });
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Harness headers preserve whole words, arrow spacing and local scrolling at doubled text size', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  fixtureAPI.get('/api/harness/items/rule', {
    items: [harnessFixture()],
    total: 1,
  });
  await page.goto('/harness/rules');
  await expect(page.getByText('release_review', { exact: true })).toBeVisible();
  const initialFonts = new Map<string, number>();
  for (const scale of [1, 2]) {
    if (scale === 2) await enlargeComputedText(page);
    for (const [name] of pairs) {
      const header = page.getByRole('columnheader', { name, exact: true });
      const control = header.getByRole('button');
      await control.scrollIntoViewIfNeeded();
      const geometry = await header.evaluate((node) => {
        const label = node.querySelector<HTMLElement>(
          '.sortable-header-label',
        )!;
        const icon = node
          .querySelector('.sortable-header-icon')!
          .getBoundingClientRect();
        const range = document.createRange();
        const text = label.firstChild!;
        const words = [...label.textContent!.matchAll(/\S+/g)].map((word) => {
          range.setStart(text, word.index!);
          range.setEnd(text, word.index! + word[0].length);
          return {
            word: word[0],
            fragments: Array.from(range.getClientRects(), (rect) => ({
              right: rect.right,
              left: rect.left,
            })),
          };
        });
        return {
          words,
          iconLeft: icon.left,
          labelRight: label.getBoundingClientRect().right,
          font: parseFloat(getComputedStyle(label).fontSize),
        };
      });
      expect(
        geometry.iconLeft - geometry.labelRight,
        `${name} arrow must stay beside its label`,
      ).toBeLessThanOrEqual(16);
      if (scale === 1) initialFonts.set(name, geometry.font);
      expect(geometry.font).toBeCloseTo(initialFonts.get(name)! * scale, 1);
      for (const word of geometry.words) {
        expect(
          word.fragments,
          `${name} must not split ${word.word} at ${scale}x`,
        ).toHaveLength(1);
        expect(word.fragments[0].right).toBeLessThanOrEqual(
          geometry.iconLeft + 0.5,
        );
      }
      await expectControlReachable(control);
      if (name === 'Updated') {
        const [controlBox, regionBox] = await Promise.all([
          control.boundingBox(),
          page
            .getByRole('region', { name: 'Rules list', exact: true })
            .boundingBox(),
        ]);
        expect(controlBox!.x).toBeGreaterThanOrEqual(regionBox!.x);
        expect(controlBox!.x + controlBox!.width).toBeLessThanOrEqual(
          regionBox!.x + regionBox!.width,
        );
      }
    }
    const grid = await page.getByRole('table').evaluate((node) => {
      const geometry = (elements: Element[]) =>
        elements.map((element) => {
          const box = element.getBoundingClientRect();
          return { x: box.x, width: box.width };
        });
      const header = node.querySelector<HTMLElement>('.harness-list-header')!;
      const row = node.querySelector<HTMLElement>('.harness-list-row')!;
      return {
        headers: geometry([...header.children]),
        cells: geometry([...row.children]),
        tableWidth: node.getBoundingClientRect().width,
        viewportWidth: node.parentElement!.clientWidth,
        scrollWidth: node.parentElement!.scrollWidth,
        headerFont: parseFloat(getComputedStyle(header).fontSize),
        rowFont: parseFloat(getComputedStyle(row).fontSize),
      };
    });
    if (scale === 1 && page.viewportSize()!.width === 1440) {
      expect(
        grid.tableWidth,
        'Normal desktop must show every Harness column without horizontal panning',
      ).toBeLessThanOrEqual(grid.viewportWidth + 0.5);
      expect(grid.scrollWidth).toBeLessThanOrEqual(grid.viewportWidth);
    }
    expect(grid.cells).toHaveLength(grid.headers.length);
    grid.headers.forEach((header, index) => {
      expect(Math.abs(header.x - grid.cells[index].x)).toBeLessThanOrEqual(0.5);
      expect(
        Math.abs(header.width - grid.cells[index].width),
      ).toBeLessThanOrEqual(0.5);
    });
    expect(grid.headerFont).toBe(grid.rowFont);
    await testInfo.attach(`harness-grid-${scale}x.json`, {
      body: JSON.stringify(grid),
      contentType: 'application/json',
    });
    await expectDocumentContained(page);
    await page
      .getByRole('region', { name: 'Rules list', exact: true })
      .evaluate((node) => {
        node.scrollLeft = 0;
      });
    const path = testInfo.outputPath(`harness-sort-headers-${scale}x.png`);
    await page.screenshot({ path });
    await testInfo.attach(`harness-sort-headers-${scale}x.png`, {
      path,
      contentType: 'image/png',
    });
    await page
      .getByRole('region', { name: 'Rules list', exact: true })
      .evaluate((node) => {
        node.scrollLeft = node.scrollWidth;
      });
    const endPath = testInfo.outputPath(
      `harness-sort-headers-end-${scale}x.png`,
    );
    await page.screenshot({ path: endPath });
    await testInfo.attach(`harness-sort-headers-end-${scale}x.png`, {
      path: endPath,
      contentType: 'image/png',
    });
  }
});
