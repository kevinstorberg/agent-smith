import { test, expect } from './fixtures';
import { defaultView, harnessViewKey, mergeViewCookie, VIEW_COOKIE_NAME } from '../src/utils/viewPreferences';

const harnessCases = [['rule', 'rules'], ['skill', 'skills'], ['tool', 'tools'], ['hook', 'hooks'], ['agent', 'agents']].map(([type, plural]) => {
  const key = harnessViewKey(type);
  return { title: plural, path: `/harness/${plural}`, api: `/api/harness/items/${type}`, counts: undefined,
    cookie: mergeViewCookie('', key, { ...defaultView(key), name: 'saved name', project: 'repo', sort: 'name', limit: 25, offset: 50 }),
    expected: { name: 'saved name', project: 'repo', sort: 'name', limit: '25', offset: '50' }, query: 'saved name' };
});
const cases = [...harnessCases,
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
    const encoded = view.cookie.slice(VIEW_COOKIE_NAME.length + 1).split(';')[0];
    await context.addCookies([{ name: VIEW_COOKIE_NAME, value: encoded, url: baseURL, sameSite: 'Lax' }]);
    await page.goto(`${view.path}?keep=1`);
    await expect(page.getByRole('textbox', { name: 'Search', exact: true })).toHaveValue(view.query);
    const requests = () => fixtureAPI.requests.filter(request => new URL(request.url).pathname === view.api);
    await expect.poll(() => requests().length).toBe(1);
    expect(Object.fromEntries(new URL(requests()[0].url).searchParams)).toEqual(view.expected);
    await page.reload();
    await expect.poll(() => requests().length).toBe(2);
    expect(Object.fromEntries(new URL(requests()[1].url).searchParams)).toEqual(view.expected);
    await expect(page.getByRole('button', { name: 'Reset view', exact: true })).toBeVisible();
  });
}
