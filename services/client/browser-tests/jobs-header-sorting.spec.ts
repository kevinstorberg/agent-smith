import { test, expect, type APIRequest } from './fixtures';
import { jobFixture } from './operationsFixture';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';

const data = (name: string) => ({
  items: [{ ...jobFixture(), name }],
  total: 30,
});

test('Job headers toggle global directions, reset paging, and retain scheduling preferences', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/jobs', ({ url }: APIRequest) =>
    data(url.searchParams.get('sort') || 'updated'),
  );
  await page.goto('/jobs?q=release&schedule_enabled=false&offset=20&keep=1');
  await expect(
    page.getByRole('cell', { name: 'updated', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Sort jobs' })).toHaveCount(
    0,
  );
  for (const [label, values] of [
    ['Name', ['name', 'name_desc']],
    ['Last Updated', ['updated', 'updated_asc']],
  ] as const) {
    const header = page.getByRole('columnheader', { name: label, exact: true });
    for (const sort of values) {
      await header.getByRole('button').click();
      await expect(
        page.getByRole('cell', { name: sort, exact: true }),
      ).toBeVisible();
      await expect(header).toHaveAttribute(
        'aria-sort',
        sort === 'name_desc' || sort === 'updated' ? 'descending' : 'ascending',
      );
      const query = new URL(
        fixtureAPI.requests
          .filter((entry) => new URL(entry.url).pathname === '/api/jobs')
          .at(-1)!.url,
      ).searchParams;
      expect(Object.fromEntries(query)).toMatchObject({
        q: 'release',
        schedule_enabled: 'false',
        offset: '0',
        sort,
      });
      expect(new URL(page.url()).searchParams.get('keep')).toBe('1');
      await page.reload();
      await expect(header).toHaveAttribute(
        'aria-sort',
        sort === 'name_desc' || sort === 'updated' ? 'descending' : 'ascending',
      );
    }
  }
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('Job keyboard sorting retains focus and rows, disables stale writes, and rejects late responses', async ({
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
  fixtureAPI.get('/api/jobs', ({ url }: APIRequest) =>
    url.searchParams.get('sort') === 'name'
      ? asc
      : url.searchParams.get('sort') === 'name_desc'
        ? desc
        : data('Accepted job'),
  );
  await page.goto('/jobs');
  await expect(
    page.getByRole('cell', { name: 'Accepted job', exact: true }),
  ).toBeVisible();
  const header = page.getByRole('columnheader', { name: 'Name', exact: true });
  const button = header.getByRole('button');
  await button.focus();
  await button.press('Enter');
  await expect(page.getByRole('table')).toHaveAttribute('aria-busy', 'true');
  await expect(
    page.getByRole('button', { name: 'Pause automatic runs for Accepted job' }),
  ).toBeDisabled();
  await expect(page.getByText('Loading...', { exact: true })).toHaveCount(0);
  await expect(button).toBeFocused();
  await button.press('Space');
  await expect
    .poll(() =>
      fixtureAPI.requests.some(
        (entry) => new URL(entry.url).searchParams.get('sort') === 'name_desc',
      ),
    )
    .toBe(true);
  resolveDesc(data('Descending job'));
  await expect(
    page.getByRole('cell', { name: 'Descending job', exact: true }),
  ).toBeVisible();
  const late = page.waitForResponse(
    (response) => new URL(response.url()).searchParams.get('sort') === 'name',
  );
  resolveAsc(data('Late job'));
  await (await late).finished();
  await expect(
    page.getByRole('cell', { name: 'Late job', exact: true }),
  ).toHaveCount(0);
  await expect(header).toHaveAttribute('aria-sort', 'descending');
  await expect(button).toBeFocused();
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

for (const font of ['computed', 'Arial']) {
  test(`Job headers remain readable with ${font} at normal and doubled text`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    fixtureAPI.get('/api/jobs', data('Release job'));
    await page.goto('/jobs');
    await expect(
      page.getByRole('cell', { name: 'Release job', exact: true }),
    ).toBeVisible();
    if (font === 'Arial')
      await page.addStyleTag({
        content: '* { font-family: Arial, sans-serif !important; }',
      });
    await expectSortableHeaderLayout(page, testInfo, {
      table: page.getByRole('table'),
      scrollRegion: page.getByRole('region', {
        name: 'Jobs list',
        exact: true,
      }),
      labels: ['Name', 'Last Updated'],
      artifactPrefix: `jobs-${font.toLowerCase()}`,
    });
  });
}
