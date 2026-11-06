import { test, expect, type APIRequest } from './fixtures';
import type { Proposal } from '../src/api';
import { proposalFixture } from './operationsFixture';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';

const rows: Proposal[] = Array.from({ length: 30 }, (_, index) => ({
  ...proposalFixture(),
  id: index + 1,
  title: `Release ${String(index + 1).padStart(2, '0')}`,
  target_name: `release_${index + 1}`,
}));
const data = (title: string) => ({ items: [{ ...rows[0], title }], total: 30 });

test('Proposal headers request both global directions at page zero and restore the current view', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/proposals/counts', {
    pending: 30,
    approved: 0,
    rejected: 0,
  });
  fixtureAPI.get('/api/proposals', ({ url }: APIRequest) => {
    const sort = url.searchParams.get('sort') || 'newest';
    const asc = sort.endsWith('_asc') || sort === 'title' || sort === 'oldest';
    const ordered = asc ? rows : [...rows].reverse();
    const offset = Number(url.searchParams.get('offset') || 0);
    const limit = Number(url.searchParams.get('limit') || 10);
    return { items: ordered.slice(offset, offset + limit), total: 30 };
  });
  await page.goto('/proposals?q=release&status=pending&offset=20&keep=1');
  await expect(
    page.getByRole('cell', { name: 'Release 10', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('combobox', { name: 'Sort proposals', exact: true }),
  ).toHaveCount(0);
  await expect(
    page
      .getByRole('columnheader', { name: 'Actions', exact: true })
      .getByRole('button'),
  ).toHaveCount(0);
  for (const [label, values] of [
    ['Title', ['title', 'title_desc']],
    ['Kind', ['kind_asc', 'kind_desc']],
    ['Action', ['action_asc', 'action_desc']],
    ['Target', ['target_asc', 'target_desc']],
    ['Created', ['newest', 'oldest']],
  ] as const) {
    const header = page.getByRole('columnheader', { name: label, exact: true });
    for (const sort of values) {
      await header.getByRole('button').click();
      await expect
        .poll(() => new URL(page.url()).searchParams.get('sort'))
        .toBe(sort);
      const asc =
        sort.endsWith('_asc') || sort === 'title' || sort === 'oldest';
      await expect(
        page.getByRole('cell', {
          name: asc ? 'Release 01' : 'Release 30',
          exact: true,
        }),
      ).toBeVisible();
      await expect(header).toHaveAttribute(
        'aria-sort',
        asc ? 'ascending' : 'descending',
      );
      const query = new URL(
        fixtureAPI.requests
          .filter((entry) => new URL(entry.url).pathname === '/api/proposals')
          .at(-1)!.url,
      ).searchParams;
      expect(Object.fromEntries(query)).toMatchObject({
        q: 'release',
        status: 'pending',
        sort,
        offset: '0',
        limit: '10',
      });
      expect(new URL(page.url()).searchParams.get('keep')).toBe('1');
      await page.reload();
      await expect(header).toHaveAttribute(
        'aria-sort',
        asc ? 'ascending' : 'descending',
      );
    }
  }
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Proposal keyboard sorting quietly retains rows and focus while protecting pending reviews from stale reads', async ({
  page,
  fixtureAPI,
}) => {
  let resolveAsc!: (value: ReturnType<typeof data>) => void;
  let resolveDesc!: (value: ReturnType<typeof data>) => void;
  const asc = new Promise<ReturnType<typeof data>>((resolve) => {
    resolveAsc = resolve;
  });
  const desc = new Promise<ReturnType<typeof data>>((resolve) => {
    resolveDesc = resolve;
  });
  fixtureAPI.get('/api/proposals/counts', {
    pending: 30,
    approved: 0,
    rejected: 0,
  });
  fixtureAPI.get('/api/proposals', ({ url }: APIRequest) =>
    url.searchParams.get('sort') === 'title'
      ? asc
      : url.searchParams.get('sort') === 'title_desc'
        ? desc
        : data('Accepted row'),
  );
  await page.goto('/proposals');
  await expect(
    page.getByRole('cell', { name: 'Accepted row', exact: true }),
  ).toBeVisible();
  const header = page.getByRole('columnheader', { name: 'Title', exact: true });
  const button = header.getByRole('button');
  await button.focus();
  await button.press('Enter');
  await expect(page.getByRole('table')).toHaveAttribute('aria-busy', 'true');
  await expect(header).not.toHaveAttribute('aria-sort');
  await expect(button).toBeFocused();
  await expect(
    page.getByRole('cell', { name: 'Accepted row', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('Loading...', { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Approve', exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole('button', { name: 'Reject', exact: true }),
  ).toBeDisabled();
  await button.press('Space');
  await expect
    .poll(
      () =>
        fixtureAPI.requests.filter(
          (entry) =>
            new URL(entry.url).searchParams.get('sort') === 'title_desc',
        ).length,
    )
    .toBe(1);
  resolveDesc(data('Accepted descending'));
  await expect(
    page.getByRole('cell', { name: 'Accepted descending', exact: true }),
  ).toBeVisible();
  const stale = page.waitForResponse(
    (response) => new URL(response.url()).searchParams.get('sort') === 'title',
  );
  resolveAsc(data('Late ascending'));
  await (await stale).finished();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  await expect(page.getByText('Late ascending', { exact: true })).toHaveCount(
    0,
  );
  await expect(header).toHaveAttribute('aria-sort', 'descending');
  await expect(button).toBeFocused();
  await expect(
    page.getByRole('button', { name: 'Approve', exact: true }),
  ).toBeEnabled();
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Proposal failure-to-header retry reports busy and preserves the empty result header focus', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/proposals/counts', {
    pending: 0,
    approved: 0,
    rejected: 0,
  });
  fixtureAPI.get('/api/proposals', { detail: 'Unavailable' }, 503);
  await page.goto('/proposals');
  await expect(page.getByRole('alert')).toContainText(
    'Could not load proposals.',
  );
  const table = page.getByRole('table');
  await expect(table).toHaveAttribute('aria-busy', 'false');
  let resolve!: (value: { items: never[]; total: number }) => void;
  const pending = new Promise<{ items: never[]; total: number }>((finish) => {
    resolve = finish;
  });
  fixtureAPI.get('/api/proposals', () => pending);
  const header = page.getByRole('columnheader', { name: 'Title', exact: true });
  const button = header.getByRole('button');
  await button.focus();
  await button.press('Enter');
  await expect(table).toHaveAttribute('aria-busy', 'true');
  await expect(header).not.toHaveAttribute('aria-sort');
  resolve({ items: [], total: 0 });
  await expect(
    page.getByText('No pending proposals', { exact: true }),
  ).toBeVisible();
  await expect(table).toHaveAttribute('aria-busy', 'false');
  await expect(header).toHaveAttribute('aria-sort', 'ascending');
  await expect(button).toBeFocused();
  await expect(table.getByRole('columnheader')).toHaveCount(6);
});

for (const fontFamily of ['computed', 'Arial'] as const) {
  test(`Proposal headers remain readable and reachable at true doubled text with ${fontFamily} font`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    fixtureAPI.get('/api/proposals/counts', {
      pending: 1,
      approved: 0,
      rejected: 0,
    });
    fixtureAPI.get('/api/proposals', data('Visible row'));
    await page.goto('/proposals');
    await expect(
      page.getByRole('cell', { name: 'Visible row', exact: true }),
    ).toBeVisible();
    if (fontFamily === 'Arial')
      await page.addStyleTag({
        content: '.proposals-list-table { font-family: Arial, sans-serif; }',
      });
    await expectSortableHeaderLayout(page, testInfo, {
      table: page.getByRole('table'),
      scrollRegion: page.getByRole('region', {
        name: 'Proposals list',
        exact: true,
      }),
      labels: ['Title', 'Kind', 'Action', 'Target', 'Created'],
      fullyVisibleHeaders: ['Title', 'Kind', 'Action', 'Target', 'Created'],
      artifactPrefix: `proposal-headers-${fontFamily.toLowerCase()}`,
    });
  });
}
