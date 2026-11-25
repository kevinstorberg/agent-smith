import { cursorMemoryConfig } from '../src/pages/__tests__/memoryFixture';
import { defaultView, mergeViewCookie } from '../src/utils/viewPreferences';
import { test, expect } from './fixtures';
import type { APIRequest } from './fixtures';
import { expectDocumentContained, expectMainContained } from './geometry';

const memory = (content: string) => ({ id: content, content });

function nativePage(content: string, next: string | null = null) {
  return {
    mode: 'cursor',
    items: [memory(content)],
    next_cursor: next,
    order: 'id_asc',
  };
}

test('native browsing requests one page per action and ignores saved offset and filters', async ({
  page,
  context,
  baseURL,
  fixtureAPI,
}) => {
  const assignment = mergeViewCookie('', 'memory', {
    ...defaultView('memory'),
    repo: 'saved-repository',
    tags: 'saved-tag',
    meeting_only: true,
    listSort: 'updated_at_desc',
    offset: 50,
  });
  const [name, value] = assignment.split(';')[0].split('=');
  await context.addCookies([{ name, value, url: baseURL! }]);
  fixtureAPI.get('/api/memory/config', cursorMemoryConfig);
  const requests: URL[] = [];
  fixtureAPI.get('/api/memory/list', ({ url }: APIRequest) => {
    requests.push(url);
    return url.searchParams.get('cursor') === 'second-token'
      ? nativePage('Second native memory')
      : nativePage('First native memory', 'second-token');
  });
  await page.goto('/memory');
  await expect(
    page.getByText('First native memory', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Memory ID order', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Repository' })).toHaveCount(
    0,
  );
  await expect(page.getByRole('combobox', { name: 'Sort' })).toHaveCount(0);
  expect(requests).toHaveLength(1);
  expect(Object.fromEntries(requests[0].searchParams)).toEqual({ limit: '10' });
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(
    page.getByText('Second native memory', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText('Page 2', { exact: true })).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(Object.fromEntries(requests[1].searchParams)).toEqual({
    limit: '10',
    cursor: 'second-token',
  });
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect.poll(() => requests.length).toBe(3);
  expect(requests[2].search).toBe(requests[1].search);
  await page.getByRole('button', { name: 'Previous', exact: true }).click();
  await expect(
    page.getByText('First native memory', { exact: true }),
  ).toBeVisible();
  expect(requests).toHaveLength(4);
  await page
    .getByRole('combobox', { name: 'Rows per page' })
    .selectOption('25');
  await expect.poll(() => requests.length).toBe(5);
  expect(Object.fromEntries(requests[4].searchParams)).toEqual({ limit: '25' });
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
  await expect(page.getByText(/Showing .* of /)).toHaveCount(0);
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('native browsing exposes filters only for bounded semantic search', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/memory/config', cursorMemoryConfig);
  fixtureAPI.get('/api/memory/list', nativePage('Native memory'));
  const searches: URL[] = [];
  fixtureAPI.get('/api/memory/search', ({ url }: APIRequest) => {
    searches.push(url);
    return { items: [memory('Semantic memory')], total: 50 };
  });
  await page.goto('/memory');
  await expect(page.getByText('Native memory', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Search memories' }).fill('release');
  await expect(
    page.getByText('Semantic memory', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Repository' })).toBeVisible();
  await expect(
    page.getByText(
      'Search results are limited to the top 50 semantic matches.',
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect
    .poll(() => searches.at(-1)?.searchParams.get('offset'))
    .toBe('10');
  expect(searches.at(-1)?.searchParams.get('cursor')).toBeNull();
  await page.getByRole('button', { name: 'Clear', exact: true }).click();
  await expect(page.getByText('Native memory', { exact: true })).toBeVisible();
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Repository' })).toHaveCount(
    0,
  );
});

test('failed cursor navigation retains the current page and can restart without traversing', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/memory/config', cursorMemoryConfig);
  let calls = 0;
  fixtureAPI.get('/api/memory/list', () => {
    calls += 1;
    return nativePage('Current native memory', 'expired-token');
  });
  await page.goto('/memory');
  await expect(
    page.getByText('Current native memory', { exact: true }),
  ).toBeVisible();
  fixtureAPI.get(
    '/api/memory/list',
    { detail: 'Cursor expired; restart from the first page' },
    422,
  );
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(
    page.getByText('Current native memory', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText('Page 1', { exact: true })).toBeVisible();
  fixtureAPI.get('/api/memory/list', () => {
    calls += 1;
    return nativePage('Restarted native memory');
  });
  await page.getByRole('button', { name: 'Restart from first page' }).click();
  await expect(
    page.getByText('Restarted native memory', { exact: true }),
  ).toBeVisible();
  expect(calls).toBe(2);
});
