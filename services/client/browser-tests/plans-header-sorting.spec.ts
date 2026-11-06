import { test, expect, type APIRequest } from './fixtures';
import { expectControlReachable, expectDocumentContained } from './geometry';
import { enlargeComputedText } from './typography';

const rows = Array.from({ length: 30 }, (_, index) => ({
  id: index + 1,
  title: `Release ${String(index + 1).padStart(2, '0')}`,
  project: 'work',
  status: 'draft',
  created_at: `2026-01-${String(index + 1).padStart(2, '0')}T12:00:00Z`,
  updated_at: `2026-01-${String(index + 1).padStart(2, '0')}T12:00:00Z`,
}));
const response = (title: string, total = 30) => ({
  items: [{ ...rows[0], title }],
  total,
});

test('Plans headers request global page-zero ordering and restore every direction after reload', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/plans', ({ url }: APIRequest) => {
    const sort = url.searchParams.get('sort');
    const ordered = sort === 'title' ? rows : [...rows].reverse();
    const offset = Number(url.searchParams.get('offset') || 0);
    const limit = Number(url.searchParams.get('limit') || 10);
    return {
      items: ordered.slice(offset, offset + limit),
      total: ordered.length,
    };
  });
  await page.goto('/plans?q=release&project=work&status=draft&keep=1');
  await expect(page.getByText('Release 30', { exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Sort plans' })).toHaveCount(
    0,
  );
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByText('Release 20', { exact: true })).toBeVisible();
  await expect(
    page.getByText('Showing 11–20 of 30', { exact: true }),
  ).toBeVisible();
  const requestStart = fixtureAPI.requests.length;
  const title = page.getByRole('columnheader', { name: 'Title' });
  await title.getByRole('button').click();
  await expect(page.getByText('Release 01', { exact: true })).toBeVisible();
  await expect(
    page.getByText('Showing 1–10 of 30', { exact: true }),
  ).toBeVisible();
  const sortedReads = fixtureAPI.requests
    .slice(requestStart)
    .filter((entry) => new URL(entry.url).pathname === '/api/plans');
  expect(sortedReads).toHaveLength(1);
  const query = new URL(sortedReads[0].url).searchParams;
  expect(Object.fromEntries(query)).toMatchObject({
    q: 'release',
    project: 'work',
    status: 'draft',
    limit: '10',
    offset: '0',
    sort: 'title',
  });
  expect(new URL(page.url()).searchParams.get('keep')).toBe('1');
  await expect(title).toHaveAttribute('aria-sort', 'ascending');
  for (const [label, sorts] of [
    ['Title', ['title_desc', 'title']],
    ['Status', ['status_asc', 'status_desc']],
    ['Project', ['project_asc', 'project_desc']],
    ['Last Updated', ['updated', 'updated_asc']],
  ] as const) {
    const header = page.getByRole('columnheader', { name: label });
    for (const sort of sorts) {
      await header.getByRole('button').click();
      await expect
        .poll(() => new URL(page.url()).searchParams.get('sort'))
        .toBe(sort);
      await expect(page.getByRole('table')).toHaveAttribute(
        'aria-busy',
        'false',
      );
      await expect(header).toHaveAttribute(
        'aria-sort',
        sort === 'updated' || sort.endsWith('_desc')
          ? 'descending'
          : 'ascending',
      );
      await page.reload();
      await expect(header).toHaveAttribute(
        'aria-sort',
        sort === 'updated' || sort.endsWith('_desc')
          ? 'descending'
          : 'ascending',
      );
      expect(new URL(page.url()).searchParams.get('q')).toBe('release');
      expect(new URL(page.url()).searchParams.get('project')).toBe('work');
      expect(new URL(page.url()).searchParams.get('status')).toBe('draft');
    }
  }
  await page.goto('/plans');
  await expect(
    page.getByRole('columnheader', { name: 'Last Updated' }),
  ).toHaveAttribute('aria-sort', 'ascending');
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Plans native keyboard sorting retains focus and rejects stale responses without false accepted indicators', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  let resolveAsc!: (value: ReturnType<typeof response>) => void;
  let resolveDesc!: (value: ReturnType<typeof response>) => void;
  const ascending = new Promise<ReturnType<typeof response>>((resolve) => {
    resolveAsc = resolve;
  });
  const descending = new Promise<ReturnType<typeof response>>((resolve) => {
    resolveDesc = resolve;
  });
  fixtureAPI.get('/api/plans', ({ url }: APIRequest) =>
    url.searchParams.get('sort') === 'title'
      ? ascending
      : url.searchParams.get('sort') === 'title_desc'
        ? descending
        : response('Initial accepted row'),
  );
  await page.goto('/plans');
  await expect(
    page.getByText('Initial accepted row', { exact: true }),
  ).toBeVisible();
  const title = page.getByRole('columnheader', { name: 'Title' });
  const button = title.getByRole('button');
  await page.getByRole('textbox', { name: 'Project scope' }).focus();
  for (
    let count = 0;
    count < 12 &&
    !(await button.evaluate((node) => node === document.activeElement));
    count++
  )
    await page.keyboard.press('Tab');
  await expect(button).toBeFocused();
  await page.keyboard.press('Enter');
  await expect
    .poll(
      () =>
        fixtureAPI.requests.filter(
          (entry) => new URL(entry.url).searchParams.get('sort') === 'title',
        ).length,
    )
    .toBe(1);
  await expect(page.getByRole('table')).toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('[aria-sort]')).toHaveCount(0);
  await expect(button).toBeFocused();
  await expect(button).toBeEnabled();
  await page.keyboard.press('Space');
  await expect
    .poll(
      () =>
        fixtureAPI.requests.filter(
          (entry) =>
            new URL(entry.url).searchParams.get('sort') === 'title_desc',
        ).length,
    )
    .toBe(1);
  resolveDesc(response('Accepted descending result', 40));
  await expect(
    page.getByText('Accepted descending result', { exact: true }),
  ).toBeVisible();
  await expect(title).toHaveAttribute('aria-sort', 'descending');
  const staleFinished = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/plans' &&
      new URL(response.url()).searchParams.get('sort') === 'title',
  );
  resolveAsc(response('Stale ascending result', 99));
  await (await staleFinished).finished();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  await expect(page.getByRole('table')).toHaveAttribute('aria-busy', 'false');
  await expect(
    page.getByText('Stale ascending result', { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText('Showing 1–10 of 40', { exact: true }),
  ).toBeVisible();
  await expect(button).toBeFocused();
  await enlargeComputedText(page);
  await expectControlReachable(button);
  await expectDocumentContained(page);
  await page.screenshot({
    path: testInfo.outputPath('plans-sorting-keyboard-2x.png'),
  });
  await testInfo.attach('plans-sorting-keyboard-2x.png', {
    path: testInfo.outputPath('plans-sorting-keyboard-2x.png'),
    contentType: 'image/png',
  });
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Plans sort labels retain whole words and separate arrows at normal and doubled text sizes', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  fixtureAPI.get('/api/plans', response('Readable heading fixture'));
  await page.goto('/plans');
  await expect(
    page.getByText('Readable heading fixture', { exact: true }),
  ).toBeVisible();
  const initialFonts = new Map<string, number>();
  for (const scale of [1, 2]) {
    if (scale === 2) await enlargeComputedText(page);
    for (const name of ['Status', 'Project', 'Last Updated']) {
      const header = page.getByRole('columnheader', { name });
      const control = header.getByRole('button');
      await control.scrollIntoViewIfNeeded();
      const geometry = await header.evaluate((node) => {
        const label = node.querySelector<HTMLElement>(
          '.sortable-header-label',
        )!;
        const icon = node
          .querySelector<HTMLElement>('.sortable-header-icon')!
          .getBoundingClientRect();
        const text = label.firstChild!;
        const range = document.createRange();
        range.selectNodeContents(label);
        const fragments = Array.from(range.getClientRects(), (rect) => ({
          left: rect.left,
          right: rect.right,
          top: rect.top,
          bottom: rect.bottom,
        }));
        const words = [...label.textContent!.matchAll(/\S+/g)].map((word) => {
          range.setStart(text, word.index!);
          range.setEnd(text, word.index! + word[0].length);
          return { word: word[0], fragments: range.getClientRects().length };
        });
        return {
          fragments,
          words,
          labelRight: label.getBoundingClientRect().right,
          icon: { left: icon.left, right: icon.right },
          font: parseFloat(getComputedStyle(label).fontSize),
        };
      });
      if (scale === 1) initialFonts.set(name, geometry.font);
      expect(geometry.font).toBeCloseTo(initialFonts.get(name)! * scale, 1);
      expect(
        geometry.words,
        `${name} must not split words at ${scale}x`,
      ).toEqual(name.split(' ').map((word) => ({ word, fragments: 1 })));
      expect(
        geometry.fragments.length,
        `${name} must use at most one line per natural word`,
      ).toBeLessThanOrEqual(name === 'Last Updated' ? 2 : 1);
      expect(
        geometry.fragments.every(
          (fragment) => fragment.right <= geometry.icon.left + 0.5,
        ),
        `${name} label must not overlap its sort arrow`,
      ).toBe(true);
      expect(
        geometry.icon.left - geometry.labelRight,
        `${name} arrow must remain beside its label`,
      ).toBeLessThanOrEqual(16);
      await expectControlReachable(control);
      if (name === 'Last Updated') {
        const [controlBox, viewportBox] = await Promise.all([
          control.boundingBox(),
          page.locator('.plans-table').boundingBox(),
        ]);
        expect(controlBox!.x).toBeGreaterThanOrEqual(viewportBox!.x);
        expect(controlBox!.x + controlBox!.width).toBeLessThanOrEqual(
          viewportBox!.x + viewportBox!.width,
        );
      }
      await testInfo.attach(
        `plans-${name.replaceAll(' ', '-')}-${scale}x-geometry.json`,
        { body: JSON.stringify(geometry), contentType: 'application/json' },
      );
    }
    await page.locator('.plans-table').evaluate((node) => {
      node.scrollLeft = 0;
    });
    await expectDocumentContained(page);
    const path = testInfo.outputPath(`plans-sort-labels-${scale}x.png`);
    await page.screenshot({ path });
    await testInfo.attach(`plans-sort-labels-${scale}x.png`, {
      path,
      contentType: 'image/png',
    });
    const dimensions = await page.locator('.plans-table').evaluate((node) => {
      const table = node.querySelector('table')!;
      return {
        viewport: node.clientWidth,
        scrollWidth: node.scrollWidth,
        table: table.getBoundingClientRect().width,
        font: parseFloat(getComputedStyle(table).fontSize),
      };
    });
    await testInfo.attach(`plans-table-${scale}x-geometry.json`, {
      body: JSON.stringify(dimensions),
      contentType: 'application/json',
    });
    await page.locator('.plans-table').evaluate((node) => {
      node.scrollLeft = node.scrollWidth;
    });
    const endPath = testInfo.outputPath(`plans-sort-labels-end-${scale}x.png`);
    await page.screenshot({ path: endPath });
    await testInfo.attach(`plans-sort-labels-end-${scale}x.png`, {
      path: endPath,
      contentType: 'image/png',
    });
  }
});
