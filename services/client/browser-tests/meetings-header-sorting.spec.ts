import { test, expect, type APIRequest } from './fixtures';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';
import { expectControlContained, expectDocumentContained } from './geometry';
import { enlargeComputedText } from './typography';
import { meetingFixture } from '../src/pages/__tests__/meetingFixture';

const pairs = [
  ['Title', 'title', 'title_desc'],
  ['Connection', 'connection_asc', 'connection_desc'],
  ['Provider', 'provider_asc', 'provider_desc'],
  ['Meeting date', 'date_asc', 'date_desc'],
  ['Last updated', 'updated_asc', 'updated'],
] as const;
const response = (title: string, total = 25) => ({
  items: [{ ...meetingFixture, title }],
  total,
});

test('Meetings headers request global filtered page-zero ordering and restore both directions', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/meetings', ({ url }: APIRequest) =>
    response(
      url.searchParams.get('sort')?.startsWith('title')
        ? 'Global first result outside previous page'
        : url.searchParams.get('offset') === '10'
          ? 'Committed second page'
          : 'Initial meeting result',
    ),
  );
  await page.goto('/meetings?q=release&labels=work&keep=1');
  await expect(
    page.getByText('Initial meeting result', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('combobox', { name: 'Sort meetings' }),
  ).toHaveCount(0);
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(
    page.getByText('Committed second page', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Showing 11–20 of 25', { exact: true }),
  ).toBeVisible();
  const start = fixtureAPI.requests.length;
  await page
    .getByRole('columnheader', { name: 'Title', exact: true })
    .getByRole('button')
    .click();
  await expect(
    page.getByText('Global first result outside previous page', {
      exact: true,
    }),
  ).toBeVisible();
  const reads = fixtureAPI.requests
    .slice(start)
    .filter((entry) => new URL(entry.url).pathname === '/api/meetings');
  expect(reads).toHaveLength(1);
  expect(Object.fromEntries(new URL(reads[0].url).searchParams)).toMatchObject({
    q: 'release',
    labels: 'work',
    offset: '0',
    limit: '10',
    sort: 'title',
  });
  for (const [name, ascending, descending] of pairs) {
    const header = page.getByRole('columnheader', { name, exact: true });
    const dates = name === 'Meeting date' || name === 'Last updated';
    const order =
      name === 'Title'
        ? [descending, ascending]
        : dates
          ? [descending, ascending]
          : [ascending, descending];
    for (const sort of order) {
      await header.getByRole('button').click();
      await expect(header).toHaveAttribute(
        'aria-sort',
        sort === ascending ? 'ascending' : 'descending',
      );
      expect(new URL(page.url()).searchParams.get('sort')).toBe(sort);
      await page.reload();
      await expect(header).toHaveAttribute(
        'aria-sort',
        sort === ascending ? 'ascending' : 'descending',
      );
      expect(
        Object.fromEntries(new URL(page.url()).searchParams),
      ).toMatchObject({ q: 'release', labels: 'work', keep: '1', offset: '0' });
    }
  }
  await page.goto('/meetings');
  await expect(
    page.getByRole('columnheader', { name: 'Last updated', exact: true }),
  ).toHaveAttribute('aria-sort', 'ascending');
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Meetings header keyboard focus survives deferred responses and rejects stale accepted state', async ({
  page,
  fixtureAPI,
}) => {
  let finishAsc!: (value: ReturnType<typeof response>) => void;
  let finishDesc!: (value: ReturnType<typeof response>) => void;
  const ascending = new Promise<ReturnType<typeof response>>((resolve) => {
    finishAsc = resolve;
  });
  const descending = new Promise<ReturnType<typeof response>>((resolve) => {
    finishDesc = resolve;
  });
  fixtureAPI.get('/api/meetings', ({ url }: APIRequest) =>
    url.searchParams.get('sort') === 'title'
      ? ascending
      : url.searchParams.get('sort') === 'title_desc'
        ? descending
        : response('Original accepted meeting'),
  );
  await page.goto('/meetings');
  await expect(
    page.getByText('Original accepted meeting', { exact: true }),
  ).toBeVisible();
  const header = page.getByRole('columnheader', { name: 'Title', exact: true });
  const button = header.getByRole('button');
  await page
    .getByRole('textbox', { name: 'Filter meetings by labels', exact: true })
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
  await expect(
    page.getByText('Loading meetings...', { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText('Original accepted meeting', { exact: true }),
  ).toBeVisible();
  await expect(page.locator('[aria-sort]')).toHaveCount(0);
  await expect(button).toBeFocused();
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
  finishDesc(response('Current descending meeting', 40));
  await expect(
    page.getByText('Current descending meeting', { exact: true }),
  ).toBeVisible();
  const stale = page.waitForResponse(
    (response) => new URL(response.url()).searchParams.get('sort') === 'title',
  );
  finishAsc(response('Stale ascending meeting', 99));
  await (await stale).finished();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  await expect(
    page.getByText('Stale ascending meeting', { exact: true }),
  ).toHaveCount(0);
  await expect(header).toHaveAttribute('aria-sort', 'descending');
  await expect(
    page.getByText('Showing 1–10 of 40', { exact: true }),
  ).toBeVisible();
  await expect(button).toBeFocused();
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Meetings empty feedback stays visible while all headers remain sortable at doubled text', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/meetings', { items: [], total: 0 });
  await page.goto('/meetings');
  const region = page.getByRole('region', {
    name: 'Meetings list',
    exact: true,
  });
  const empty = region.getByRole('status');
  await expect(empty).toHaveText(
    'No meeting summaries saved yet. Run your meeting import job from Jobs.',
  );
  await expect(region.getByRole('columnheader')).toHaveCount(5);
  const initialFont = await empty.evaluate((node) =>
    parseFloat(getComputedStyle(node).fontSize),
  );
  await enlargeComputedText(page);
  expect(
    await empty.evaluate((node) => parseFloat(getComputedStyle(node).fontSize)),
  ).toBeCloseTo(initialFont * 2, 1);
  for (const end of [false, true]) {
    await region.evaluate((node, end) => {
      node.scrollLeft = end ? node.scrollWidth : 0;
    }, end);
    await expectControlContained(empty, region);
    const text = await empty.evaluate((node) => {
      const range = document.createRange();
      range.selectNodeContents(node);
      const rect = node.getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        fragments: [...range.getClientRects()].map((rect) => ({
          left: rect.left,
          right: rect.right,
        })),
      };
    });
    for (const fragment of text.fragments) {
      expect(fragment.left).toBeGreaterThanOrEqual(text.left);
      expect(fragment.right).toBeLessThanOrEqual(text.right);
    }
  }
  const header = region.getByRole('columnheader', {
    name: 'Last updated',
    exact: true,
  });
  await header.getByRole('button').click();
  await expect(header).toHaveAttribute('aria-sort', 'descending');
  await expect(empty).toBeVisible();
  await expectDocumentContained(page);
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

for (const font of ['computed font', 'Arial fallback'] as const) {
  test(`Meetings headers remain readable and aligned at normal and doubled text sizes with ${font}`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    fixtureAPI.get(
      '/api/meetings',
      response('Readable meeting heading fixture'),
    );
    await page.goto('/meetings');
    await expect(
      page.getByText('Readable meeting heading fixture', { exact: true }),
    ).toBeVisible();
    if (font === 'Arial fallback')
      await page.getByRole('table').evaluate((node) => {
        (node as HTMLElement).style.fontFamily = 'Arial, sans-serif';
        node.parentElement!.style.fontFamily = 'Arial, sans-serif';
      });
    await expectSortableHeaderLayout(page, testInfo, {
      table: page.getByRole('table'),
      scrollRegion: page.getByRole('region', {
        name: 'Meetings list',
        exact: true,
      }),
      labels: pairs.map(([name]) => name),
      artifactPrefix: 'meetings-sort-headers',
      fullyVisibleHeaders: [
        'Connection',
        'Provider',
        'Meeting date',
        'Last updated',
      ],
      assertLayout: async (scale) => {
        const layout = await page.getByRole('table').evaluate((node) => {
          const cells = (nodes: Element[]) =>
            nodes.map((cell) => {
              const box = cell.getBoundingClientRect();
              return { x: box.x, width: box.width };
            });
          return {
            header: cells([...node.querySelectorAll('thead th')]),
            row: cells([...node.querySelectorAll('tbody tr:first-child td')]),
            width: node.getBoundingClientRect().width,
            viewport: node.parentElement!.clientWidth,
          };
        });
        layout.header.forEach((header, index) => {
          expect(Math.abs(header.x - layout.row[index].x)).toBeLessThanOrEqual(
            0.5,
          );
          expect(
            Math.abs(header.width - layout.row[index].width),
          ).toBeLessThanOrEqual(0.5);
        });
        if (scale === 1 && page.viewportSize()!.width === 1440)
          expect(layout.width).toBeLessThanOrEqual(layout.viewport);
        await testInfo.attach(`meetings-grid-${scale}x.json`, {
          body: JSON.stringify(layout),
          contentType: 'application/json',
        });
      },
    });
  });
}
