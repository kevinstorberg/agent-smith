import { test, expect } from './fixtures';
import { defaultView, harnessViewKey, mergeViewCookie, VIEW_COOKIE_NAME } from '../src/utils/viewPreferences';

interface PreferenceCase {
  title: string; path: string; api: string; cookie: string; expected: Record<string, string>; query: string;
  fixtures?: { path: string; body: unknown }[]; queryLabel?: string; counts?: { path: string; body: Record<string, number> };
}

const harnessCases = [['rule', 'rules'], ['skill', 'skills'], ['tool', 'tools'], ['hook', 'hooks'], ['agent', 'agents']].map(([type, plural]) => {
  const key = harnessViewKey(type);
  return { title: plural, path: `/harness/${plural}`, api: `/api/harness/items/${type}`, counts: undefined,
    cookie: mergeViewCookie('', key, { ...defaultView(key), name: 'saved name', project: 'repo', sort: 'name', limit: 25, offset: 50 }),
    expected: { name: 'saved name', project: 'repo', sort: 'name', limit: '25', offset: '50' }, query: 'saved name' };
});
const cases: PreferenceCase[] = [...harnessCases,
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
  { title: 'Audit', path: '/audit', api: '/api/audit/events', counts: { path: '/api/audit/counts', body: { claude: 0, codex: 0, gemini: 0 } },
    cookie: mergeViewCookie('', 'audit', { ...defaultView('audit'), q: 'Read', project: 'repo', agent: 'codex', status: 'error', sort: 'duration', limit: 25, offset: 50 }),
    expected: { q: 'Read', project: 'repo', agent: 'codex', status: 'error', sort: 'duration', limit: '25', offset: '50' }, query: 'Read' },
  { title: 'Proposals', path: '/proposals', api: '/api/proposals', counts: { path: '/api/proposals/counts', body: { pending: 0, approved: 0, rejected: 0 } },
    cookie: mergeViewCookie('', 'proposals', { ...defaultView('proposals'), q: 'review', status: 'approved', sort: 'oldest', limit: 25, offset: 50 }),
    expected: { q: 'review', status: 'approved', sort: 'oldest', limit: '25', offset: '50' }, query: 'review' },
  { title: 'Eval suites', path: '/eval-configs', api: '/api/eval-configs/suites', counts: undefined,
    cookie: mergeViewCookie('', 'evalSuites', { ...defaultView('evalSuites'), q: 'quality', enabled: 'false', sort: 'updated', limit: 25, offset: 50 }),
    expected: { q: 'quality', enabled: 'false', enabled_only: 'false', sort: 'updated', limit: '25', offset: '50' }, query: 'quality' },
];

for (const view of cases) {
  test(`${view.title} restores its cookie before requesting data and retains it on reload`, async ({ page, context, fixtureAPI, baseURL }) => {
    if (!baseURL) throw new Error('Preference browser tests require the owned preview');
    fixtureAPI.get(view.api, { items: [], total: 100 });
    if (view.counts) fixtureAPI.get(view.counts.path, view.counts.body);
    for (const fixture of view.fixtures ?? []) fixtureAPI.get(fixture.path, fixture.body);
    const encoded = view.cookie.slice(VIEW_COOKIE_NAME.length + 1).split(';')[0];
    await context.addCookies([{ name: VIEW_COOKIE_NAME, value: encoded, url: baseURL, sameSite: 'Lax' }]);
    const target = new URL(view.path, baseURL);
    target.searchParams.set('keep', '1');
    await page.goto(target.href);
    await expect(page.getByLabel(view.queryLabel ?? 'Search', { exact: true })).toHaveValue(view.query);
    const requests = () => fixtureAPI.requests.filter(request => new URL(request.url).pathname === view.api);
    await expect.poll(() => requests().length).toBe(1);
    expect(Object.fromEntries(new URL(requests()[0].url).searchParams)).toEqual(view.expected);
    await page.reload();
    await expect.poll(() => requests().length).toBe(2);
    expect(Object.fromEntries(new URL(requests()[1].url).searchParams)).toEqual(view.expected);
    await expect(page.getByRole('button', { name: 'Reset view', exact: true })).toBeVisible();
  });
}
