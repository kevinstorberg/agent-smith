import { test, expect, type APIRequest } from './fixtures';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';
import { expectControlContained, expectDocumentContained } from './geometry';
import { enlargeComputedText } from './typography';

const term = {
  id: 'c06a7e41-1122-4344-8566-bb2233445566',
  term: 'LTV',
  definition: 'Lifetime value',
  revision: 3,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};
const response = (name = 'LTV', total = 25) => ({
  items: [{ ...term, term: name }],
  total,
});
const pairs = [
  ['Term', 'term', 'term_desc'],
  ['Meaning', 'definition_asc', 'definition_desc'],
] as const;
const path = '/api/meetings/vocabulary';

test('Vocabulary headers order the complete filtered page and persist both directions without writes', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get(path, ({ url }: APIRequest) =>
    response(
      url.searchParams.get('sort') === 'term_desc'
        ? 'Global result outside prior page'
        : url.searchParams.get('offset') === '10'
          ? 'Committed second page'
          : 'LTV',
    ),
  );
  await page.goto(
    '/meetings?tab=vocabulary&q=financial&definition=defined&keep=1',
  );
  await expect(
    page.getByRole('button', { name: 'Edit LTV', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('combobox', { name: 'Sort vocabulary' }),
  ).toHaveCount(0);
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(
    page.getByText('Committed second page', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Showing 11–20 of 25', { exact: true }),
  ).toBeVisible();
  await page
    .getByRole('columnheader', { name: 'Term', exact: true })
    .getByRole('button')
    .click();
  await expect(
    page.getByText('Global result outside prior page', { exact: true }),
  ).toBeVisible();
  expect(
    Object.fromEntries(
      new URL(
        fixtureAPI.requests
          .filter((entry) => new URL(entry.url).pathname === path)
          .at(-1)!.url,
      ).searchParams,
    ),
  ).toMatchObject({
    sort: 'term_desc',
    offset: '0',
    limit: '10',
    q: 'financial',
    definition: 'defined',
  });
  for (const [name, ascending, descending] of pairs) {
    const header = page.getByRole('columnheader', { name, exact: true });
    const current = new URL(page.url()).searchParams.get('sort');
    const first = current === ascending ? descending : ascending;
    for (const sort of [first, first === ascending ? descending : ascending]) {
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
      ).toMatchObject({
        tab: 'vocabulary',
        q: 'financial',
        definition: 'defined',
        keep: '1',
        offset: '0',
      });
    }
  }
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Vocabulary keyboard sorting retains focus and rows and refuses an older response', async ({
  page,
  fixtureAPI,
}) => {
  let finishAsc!: (value: ReturnType<typeof response>) => void;
  let finishDesc!: (value: ReturnType<typeof response>) => void;
  const asc = new Promise<ReturnType<typeof response>>((resolve) => {
    finishAsc = resolve;
  });
  const desc = new Promise<ReturnType<typeof response>>((resolve) => {
    finishDesc = resolve;
  });
  fixtureAPI.get(path, ({ url }: APIRequest) =>
    url.searchParams.get('sort') === 'definition_asc'
      ? asc
      : url.searchParams.get('sort') === 'definition_desc'
        ? desc
        : response(),
  );
  await page.goto('/meetings?tab=vocabulary');
  await expect(page.getByText('Lifetime value', { exact: true })).toBeVisible();
  const table = page.getByRole('table', {
    name: 'Vocabulary terms',
    exact: true,
  });
  const header = table.getByRole('columnheader', {
    name: 'Meaning',
    exact: true,
  });
  const button = header.getByRole('button');
  await page.getByRole('combobox', { name: 'Definition', exact: true }).focus();
  for (
    let count = 0;
    count < 12 &&
    !(await button.evaluate((node) => node === document.activeElement));
    count++
  )
    await page.keyboard.press('Tab');
  await expect(button).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(table).toHaveAttribute('aria-busy', 'true');
  await expect(table.locator('[aria-sort]')).toHaveCount(0);
  await expect(
    page.getByText('Loading vocabulary...', { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText('Lifetime value', { exact: true })).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Edit LTV', exact: true }),
  ).toBeDisabled();
  await page.keyboard.press('Space');
  await expect
    .poll(() =>
      fixtureAPI.requests.some(
        (entry) =>
          new URL(entry.url).searchParams.get('sort') === 'definition_desc',
      ),
    )
    .toBe(true);
  finishDesc(response('Current descending', 40));
  await expect(
    page.getByText('Current descending', { exact: true }),
  ).toBeVisible();
  const stale = page.waitForResponse(
    (result) =>
      new URL(result.url()).searchParams.get('sort') === 'definition_asc',
  );
  finishAsc(response('Stale ascending', 99));
  await (await stale).finished();
  await expect(page.getByText('Stale ascending', { exact: true })).toHaveCount(
    0,
  );
  await expect(header).toHaveAttribute('aria-sort', 'descending');
  await expect(button).toBeFocused();
  await expect(
    page.getByText('Showing 1–10 of 40', { exact: true }),
  ).toBeVisible();
});

test('Vocabulary sorting preserves a draft and freezes headers during its revision-checked save', async ({
  page,
  fixtureAPI,
}) => {
  let current = term;
  fixtureAPI.get(path, () => ({ items: [current], total: 1 }));
  let finish!: (value: typeof term) => void;
  const saved = new Promise<typeof term>((resolve) => {
    finish = resolve;
  });
  let body: unknown;
  fixtureAPI.mock('PATCH', `${path}/${term.id}`, ({ request }: APIRequest) => {
    body = request.postDataJSON();
    return saved;
  });
  await page.goto('/meetings?tab=vocabulary');
  await page.getByRole('button', { name: 'Edit LTV', exact: true }).click();
  const draft = page.getByRole('textbox', {
    name: 'Meaning / definition (optional)',
    exact: true,
  });
  await draft.fill('Retained draft meaning');
  const table = page.getByRole('table', {
    name: 'Vocabulary terms',
    exact: true,
  });
  await table
    .getByRole('columnheader', { name: 'Meaning', exact: true })
    .getByRole('button')
    .click();
  await expect(
    table.getByRole('columnheader', { name: 'Meaning', exact: true }),
  ).toHaveAttribute('aria-sort', 'ascending');
  await expect(draft).toHaveValue('Retained draft meaning');
  await page.getByRole('button', { name: 'Save term', exact: true }).click();
  await expect
    .poll(() => body)
    .toEqual({
      term: 'LTV',
      definition: 'Retained draft meaning',
      expected_revision: 3,
    });
  for (const [name] of pairs)
    await expect(
      table
        .getByRole('columnheader', { name, exact: true })
        .getByRole('button'),
    ).toBeDisabled();
  current = { ...term, definition: 'Retained draft meaning', revision: 4 };
  finish(current);
  await expect(
    table.getByText('Retained draft meaning', { exact: true }),
  ).toBeVisible();
  await expect(
    table
      .getByRole('columnheader', { name: 'Term', exact: true })
      .getByRole('button'),
  ).toBeEnabled();
  expect(
    fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
  ).toHaveLength(1);
});

test('Vocabulary empty/error recovery keeps headers operable and never labels a pending query empty', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get(path, { detail: 'Synthetic read failure' }, 500);
  await page.goto('/meetings?tab=vocabulary');
  await expect(page.getByRole('alert')).toContainText(
    'Could not load vocabulary.',
  );
  const region = page.getByRole('region', {
    name: 'Vocabulary terms',
    exact: true,
  });
  await expect(region.getByRole('columnheader')).toHaveCount(3);
  await expect(region.getByRole('table')).toHaveAttribute('aria-busy', 'false');
  const emptyPage = { items: [], total: 0 };
  let finish!: (value: typeof emptyPage) => void;
  const pending = new Promise<typeof emptyPage>((resolve) => {
    finish = resolve;
  });
  fixtureAPI.get(path, ({ url }: APIRequest) =>
    url.searchParams.get('q') === 'new query' ? pending : emptyPage,
  );
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  const empty = region.getByRole('status');
  await expect(empty).toHaveText('No vocabulary terms yet.');
  await enlargeComputedText(page);
  for (const end of [false, true]) {
    await region.evaluate((node, end) => {
      node.scrollLeft = end ? node.scrollWidth : 0;
    }, end);
    await expectControlContained(empty, region);
  }
  await page
    .getByRole('textbox', { name: 'Search vocabulary', exact: true })
    .fill('new query');
  await expect
    .poll(() =>
      fixtureAPI.requests.some(
        (entry) => new URL(entry.url).searchParams.get('q') === 'new query',
      ),
    )
    .toBe(true);
  await expect(empty).toHaveCount(0);
  await expect(
    page.getByText('No vocabulary terms match your search.', { exact: true }),
  ).toHaveCount(0);
  await expect(region.getByRole('table')).toHaveAttribute('aria-busy', 'true');
  await expect(
    page.getByText('Loading vocabulary...', { exact: true }),
  ).toHaveCount(0);
  finish(emptyPage);
  await expect(empty).toHaveText('No vocabulary terms match your search.');
  await expectDocumentContained(page);
});

for (const font of ['computed font', 'Arial fallback'] as const) {
  test(`Vocabulary sort headers remain whole and reachable at normal and doubled ${font}`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    fixtureAPI.get(path, response());
    await page.goto('/meetings?tab=vocabulary');
    const table = page.getByRole('table', {
      name: 'Vocabulary terms',
      exact: true,
    });
    await expect(
      table.getByText('Lifetime value', { exact: true }),
    ).toBeVisible();
    if (font === 'Arial fallback')
      await table.evaluate((node) => {
        (node as HTMLElement).style.fontFamily = 'Arial, sans-serif';
        node.parentElement!.style.fontFamily = 'Arial, sans-serif';
      });
    await expectSortableHeaderLayout(page, testInfo, {
      table,
      scrollRegion: page.getByRole('region', {
        name: 'Vocabulary terms',
        exact: true,
      }),
      labels: ['Term', 'Meaning'],
      fullyVisibleHeaders: ['Term', 'Meaning'],
      artifactPrefix: 'vocabulary-sort-headers',
    });
  });
}
