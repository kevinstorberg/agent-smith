import { test, expect } from './fixtures';
import { defaultView, mergeViewCookie, VIEW_COOKIE_NAME } from '../src/utils/viewPreferences';

interface PreferenceCase {
  title: string; path: string; api: string; cookie: string; expected: Record<string, string>; query: string;
  queryLabel: string;
}

const cases: PreferenceCase[] = [
  { title: 'Memory list', path: '/memory', api: '/api/memory/list', queryLabel: 'Search memories',
    cookie: mergeViewCookie('', 'memory', { ...defaultView('memory'), listSort: 'updated_at_asc', repo: 'repo', limit: 25, offset: 50 }),
    expected: { repo: 'repo', meeting_only: 'false', sort: 'updated_at_asc', limit: '25', offset: '50' }, query: '' },
  { title: 'Memory search', path: '/memory', api: '/api/memory/search', queryLabel: 'Search memories',
    cookie: mergeViewCookie('', 'memory', { ...defaultView('memory'), q: 'release', repo: 'repo', tags: 'decision', meeting_only: true, searchSort: 'created_at_asc', limit: 25, offset: 50 }),
    expected: { q: 'release', repo: 'repo', tags: 'decision', meeting_only: 'true', sort: 'created_at_asc', limit: '25', offset: '50' }, query: 'release' },
  { title: 'Meetings', path: '/meetings', api: '/api/meetings', queryLabel: 'Search meetings',
    cookie: mergeViewCookie('', 'meetings', { ...defaultView('meetings'), q: 'planning', labels: 'release', sort: 'title', limit: 25, offset: 50 }),
    expected: { q: 'planning', labels: 'release', sort: 'title', limit: '25', offset: '50' }, query: 'planning' },
  { title: 'Vocabulary', path: '/meetings?tab=vocabulary', api: '/api/meetings/vocabulary', queryLabel: 'Search vocabulary',
    cookie: mergeViewCookie('', 'vocabulary', { ...defaultView('vocabulary'), q: 'term', definition: 'defined', sort: 'updated', limit: 25, offset: 50 }),
    expected: { q: 'term', definition: 'defined', sort: 'updated', limit: '25', offset: '50' }, query: 'term' },
];

for (const view of cases) {
  test(`${view.title} restores its cookie before requesting data and retains it on reload`, async ({ page, context, fixtureAPI, baseURL }) => {
    if (!baseURL) throw new Error('Preference browser tests require the owned preview');
    fixtureAPI.get(view.api, { items: [], total: 100 });
    const encoded = view.cookie.slice(VIEW_COOKIE_NAME.length + 1).split(';')[0];
    await context.addCookies([{ name: VIEW_COOKIE_NAME, value: encoded, url: baseURL, sameSite: 'Lax' }]);
    const target = new URL(view.path, baseURL);
    target.searchParams.set('keep', '1');
    await page.goto(target.href);
    await expect(page.getByRole('textbox', { name: view.queryLabel, exact: true })).toHaveValue(view.query);
    const requests = () => fixtureAPI.requests.filter(request => new URL(request.url).pathname === view.api);
    await expect.poll(() => requests().length).toBe(1);
    expect(Object.fromEntries(new URL(requests()[0].url).searchParams)).toEqual(view.expected);
    await page.reload();
    await expect.poll(() => requests().length).toBe(2);
    expect(Object.fromEntries(new URL(requests()[1].url).searchParams)).toEqual(view.expected);
    await expect(page.getByRole('button', { name: 'Reset view', exact: true })).toBeVisible();
  });
}

test('Memory sequential typing preserves the full applied search and independent list sorting', async ({ page, fixtureAPI }) => {
  fixtureAPI.get('/api/memory/list', { items: [], total: 0 });
  fixtureAPI.get('/api/memory/search', { items: [], total: 0 });
  await page.goto('/memory');
  const input = page.getByRole('textbox', { name: 'Search memories', exact: true });
  await page.getByRole('combobox', { name: 'Sort', exact: true }).selectOption('updated_at_asc');
  await input.pressSequentially('release details', { delay: 10 });
  await expect(input).toHaveValue('release details');
  const searches = () => fixtureAPI.requests.filter(request => new URL(request.url).pathname === '/api/memory/search');
  await expect.poll(() => searches().at(-1) ? new URL(searches().at(-1)!.url).searchParams.get('q') : null).toBe('release details');
  await page.reload();
  await expect(input).toHaveValue('release details');
  await page.getByRole('button', { name: 'Clear', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Sort', exact: true })).toHaveValue('updated_at_asc');
  const lists = () => fixtureAPI.requests.filter(request => new URL(request.url).pathname === '/api/memory/list');
  await expect.poll(() => new URL(lists().at(-1)!.url).searchParams.get('sort')).toBe('updated_at_asc');
});

test('Meeting tab links restore their own saved query and page without sharing criteria', async ({ page, context, fixtureAPI, baseURL }) => {
  if (!baseURL) throw new Error('Preference browser tests require the owned preview');
  fixtureAPI.get('/api/meetings', { items: [], total: 100 });
  fixtureAPI.get('/api/meetings/vocabulary', { items: [], total: 100 });
  let cookie = mergeViewCookie('', 'meetings', { ...defaultView('meetings'), q: 'meeting query', sort: 'title', limit: 25, offset: 50 });
  cookie = mergeViewCookie(cookie, 'vocabulary', { ...defaultView('vocabulary'), q: 'vocabulary query', sort: 'updated', limit: 50, offset: 50 });
  await context.addCookies([{ name: VIEW_COOKIE_NAME, value: cookie.slice(VIEW_COOKIE_NAME.length + 1).split(';')[0], url: baseURL, sameSite: 'Lax' }]);
  await page.goto('/meetings?keep=1');
  await expect(page.getByRole('textbox', { name: 'Search meetings' })).toHaveValue('meeting query');
  await page.getByRole('navigation', { name: 'Meeting views' }).getByRole('link', { name: 'Vocabulary', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Search vocabulary' })).toHaveValue('vocabulary query');
  const vocab = () => fixtureAPI.requests.filter(request => new URL(request.url).pathname === '/api/meetings/vocabulary');
  await expect.poll(() => vocab().length).toBe(1);
  expect(new URL(vocab()[0].url).searchParams.get('offset')).toBe('50');
  await page.getByRole('combobox', { name: 'Sort vocabulary' }).selectOption('term');
  await page.getByRole('navigation', { name: 'Meeting views' }).getByRole('link', { name: 'Meetings', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Search meetings' })).toHaveValue('meeting query');
  await expect(page.getByRole('combobox', { name: 'Sort meetings' })).toHaveValue('title');
  const meetings = () => fixtureAPI.requests.filter(request => new URL(request.url).pathname === '/api/meetings');
  await expect.poll(() => meetings().length).toBe(2);
  expect(new URL(meetings()[1].url).searchParams.get('offset')).toBe('50');
  expect(new URL(page.url()).searchParams.get('keep')).toBe('1');
});
