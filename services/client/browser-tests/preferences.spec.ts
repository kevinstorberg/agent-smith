import { test, expect } from './fixtures';
import { defaultView, mergeViewCookie, VIEW_COOKIE_NAME } from '../src/utils/viewPreferences';

interface PreferenceCase {
  title: string; path: string; api: string; cookie: string; expected: Record<string, string>; query: string;
  fixtures?: { path: string; body: unknown }[]; queryLabel: string;
}

const cases: PreferenceCase[] = [
  { title: 'Action items', path: '/action-items', api: '/api/action-items', queryLabel: 'Search action items',
    cookie: mergeViewCookie('', 'actionItems', { ...defaultView('actionItems'), q: 'review', project: 'repo', tags: 'urgent', sort: 'title', limit: 25, offset: 50 }),
    expected: { status: 'open', q: 'review', project: 'repo', tags: 'urgent', sort: 'title', limit: '25', offset: '50' }, query: 'review' },
  { title: 'Profiles', path: '/profiles', api: '/api/profiles', queryLabel: 'Search profiles', fixtures: [{ path: '/api/jobs/graph/persona', body: { items: [], total: 0 } }],
    cookie: mergeViewCookie('', 'profiles', { ...defaultView('profiles'), q: 'person', tags: 'team', starred: true, sort: 'name_desc', limit: 25, offset: 50 }),
    expected: { q: 'person', tags: 'team', starred: 'true', sort: 'name_desc', limit: '25', offset: '50' }, query: 'person' },
  { title: 'Chat', path: '/chat', api: '/api/chat', queryLabel: 'Search rooms', fixtures: [{ path: '/api/chat/config', body: { participants: [] } }],
    cookie: mergeViewCookie('', 'chat', { ...defaultView('chat'), q: 'topic', status: 'closed', sort: 'name', limit: 25, offset: 50 }),
    expected: { q: 'topic', status: 'closed', sort: 'name', limit: '25', offset: '50' }, query: 'topic' },
  { title: 'Results', path: '/evals', api: '/api/evals', queryLabel: 'Search', fixtures: [
      { path: '/api/evals/categories', body: ['rules'] }, { path: '/api/evals/subcategories', body: [] },
      { path: '/api/evals/facets', body: { scenarios: [], models: [] } }, { path: '/api/evals/chart/average', body: [] },
    ], cookie: mergeViewCookie('', 'results', { ...defaultView('results'), q: 'check', category: 'rules', subcategory: 'core', scenario: 'scenario', model: 'test-model', sort: 'score', limit: 25, offset: 50 }),
    expected: { q: 'check', eval_type: 'rules', subcategory: 'core', scenario: 'scenario', model: 'test-model', sort: 'score', limit: '25', offset: '50' }, query: 'check' },
];

for (const view of cases) {
  test(`${view.title} restores its cookie before requesting data and retains it on reload`, async ({ page, context, fixtureAPI, baseURL }) => {
    if (!baseURL) throw new Error('Preference browser tests require the owned preview');
    fixtureAPI.get(view.api, { items: [], total: 100 });
    for (const fixture of view.fixtures ?? []) fixtureAPI.get(fixture.path, fixture.body);
    const encoded = view.cookie.slice(VIEW_COOKIE_NAME.length + 1).split(';')[0];
    await context.addCookies([{ name: VIEW_COOKIE_NAME, value: encoded, url: baseURL, sameSite: 'Lax' }]);
    const target = new URL(view.path, baseURL);
    target.searchParams.set('keep', '1');
    await page.goto(target.href);
    await expect(page.getByLabel(view.queryLabel, { exact: true })).toHaveValue(view.query);
    const requests = () => fixtureAPI.requests.filter(request => new URL(request.url).pathname === view.api);
    await expect.poll(() => requests().length).toBe(1);
    expect(Object.fromEntries(new URL(requests()[0].url).searchParams)).toEqual(view.expected);
    await page.reload();
    await expect.poll(() => requests().length).toBe(2);
    expect(Object.fromEntries(new URL(requests()[1].url).searchParams)).toEqual(view.expected);
    await expect(page.getByRole('button', { name: 'Reset view', exact: true })).toBeVisible();
  });
}
