import { test, expect } from './fixtures';
import {
  defaultView,
  harnessViewKey,
  mergeViewCookie,
  VIEW_COOKIE_NAME,
} from '../src/utils/viewPreferences';

interface PreferenceCase {
  title: string;
  path: string;
  api: string;
  cookie: string;
  expected: Record<string, string>;
  query: string;
  fixtures?: { path: string; body: unknown }[];
  counts?: { path: string; body: Record<string, number> };
  queryLabel?: string;
}

const harnessCases = [
  ['rule', 'rules'],
  ['skill', 'skills'],
  ['tool', 'tools'],
  ['hook', 'hooks'],
  ['agent', 'agents'],
].map(([type, plural]) => {
  const key = harnessViewKey(type);
  return {
    title: plural,
    path: `/harness/${plural}`,
    api: `/api/harness/items/${type}`,
    counts: undefined,
    cookie: mergeViewCookie('', key, {
      ...defaultView(key),
      name: 'saved name',
      project: 'repo',
      sort: 'name',
      limit: 25,
      offset: 50,
    }),
    expected: {
      name: 'saved name',
      project: 'repo',
      sort: 'name',
      limit: '25',
      offset: '50',
    },
    query: 'saved name',
  };
});
const cases: PreferenceCase[] = [
  ...harnessCases,
  {
    title: 'Action items',
    path: '/action-items',
    api: '/api/action-items',
    queryLabel: 'Search action items',
    cookie: mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      q: 'review',
      project: 'repo',
      tags: 'urgent',
      sort: 'title',
      limit: 25,
      offset: 50,
    }),
    expected: {
      status: 'open',
      q: 'review',
      project: 'repo',
      tags: 'urgent',
      sort: 'title',
      limit: '25',
      offset: '50',
    },
    query: 'review',
  },
  {
    title: 'Profiles',
    path: '/profiles',
    api: '/api/profiles',
    queryLabel: 'Search profiles',
    fixtures: [
      { path: '/api/jobs/graph/persona', body: { items: [], total: 0 } },
    ],
    cookie: mergeViewCookie('', 'profiles', {
      ...defaultView('profiles'),
      q: 'person',
      tags: 'team',
      starred: true,
      sort: 'name_desc',
      limit: 25,
      offset: 50,
    }),
    expected: {
      q: 'person',
      tags: 'team',
      starred: 'true',
      sort: 'name_desc',
      limit: '25',
      offset: '50',
    },
    query: 'person',
  },
  {
    title: 'Chat',
    path: '/chat',
    api: '/api/chat',
    queryLabel: 'Search rooms',
    fixtures: [{ path: '/api/chat/config', body: { participants: [] } }],
    cookie: mergeViewCookie('', 'chat', {
      ...defaultView('chat'),
      q: 'topic',
      status: 'closed',
      sort: 'name',
      limit: 25,
      offset: 50,
    }),
    expected: {
      q: 'topic',
      status: 'closed',
      sort: 'name',
      limit: '25',
      offset: '50',
    },
    query: 'topic',
  },
  {
    title: 'Results',
    path: '/evals',
    api: '/api/evals',
    fixtures: [
      { path: '/api/evals/categories', body: ['rules'] },
      { path: '/api/evals/subcategories', body: [] },
      { path: '/api/evals/facets', body: { scenarios: [], models: [] } },
      { path: '/api/evals/chart/average', body: [] },
    ],
    cookie: mergeViewCookie('', 'results', {
      ...defaultView('results'),
      q: 'check',
      category: 'rules',
      subcategory: 'core',
      scenario: 'scenario',
      model: 'test-model',
      sort: 'score',
      limit: 25,
      offset: 50,
    }),
    expected: {
      q: 'check',
      eval_type: 'rules',
      subcategory: 'core',
      scenario: 'scenario',
      model: 'test-model',
      sort: 'score',
      limit: '25',
      offset: '50',
    },
    query: 'check',
  },
  {
    title: 'Audit',
    path: '/audit',
    api: '/api/audit/events',
    counts: {
      path: '/api/audit/counts',
      body: { claude: 0, codex: 0, gemini: 0 },
    },
    cookie: mergeViewCookie('', 'audit', {
      ...defaultView('audit'),
      q: 'Read',
      project: 'repo',
      agent: 'codex',
      status: 'error',
      sort: 'duration',
      limit: 25,
      offset: 50,
    }),
    expected: {
      q: 'Read',
      project: 'repo',
      agent: 'codex',
      status: 'error',
      sort: 'duration',
      limit: '25',
      offset: '50',
    },
    query: 'Read',
  },
  {
    title: 'Proposals',
    path: '/proposals',
    api: '/api/proposals',
    counts: {
      path: '/api/proposals/counts',
      body: { pending: 0, approved: 0, rejected: 0 },
    },
    cookie: mergeViewCookie('', 'proposals', {
      ...defaultView('proposals'),
      q: 'review',
      status: 'approved',
      sort: 'oldest',
      limit: 25,
      offset: 50,
    }),
    expected: {
      q: 'review',
      status: 'approved',
      sort: 'oldest',
      limit: '25',
      offset: '50',
    },
    query: 'review',
  },
  {
    title: 'Eval suites',
    path: '/eval-configs',
    api: '/api/eval-configs/suites',
    counts: undefined,
    cookie: mergeViewCookie('', 'evalSuites', {
      ...defaultView('evalSuites'),
      q: 'quality',
      enabled: 'false',
      sort: 'updated',
      limit: 25,
      offset: 50,
    }),
    expected: {
      q: 'quality',
      enabled: 'false',
      enabled_only: 'false',
      sort: 'updated',
      limit: '25',
      offset: '50',
    },
    query: 'quality',
  },
  {
    title: 'Memory list',
    path: '/memory',
    api: '/api/memory/list',
    queryLabel: 'Search memories',
    cookie: mergeViewCookie('', 'memory', {
      ...defaultView('memory'),
      listSort: 'updated_at_asc',
      repo: 'repo',
      limit: 25,
      offset: 50,
    }),
    expected: {
      repo: 'repo',
      meeting_only: 'false',
      sort: 'updated_at_asc',
      limit: '25',
      offset: '50',
    },
    query: '',
  },
  {
    title: 'Memory search',
    path: '/memory',
    api: '/api/memory/search',
    queryLabel: 'Search memories',
    cookie: mergeViewCookie('', 'memory', {
      ...defaultView('memory'),
      q: 'release',
      repo: 'repo',
      tags: 'decision',
      meeting_only: true,
      searchSort: 'created_at_asc',
      limit: 25,
      offset: 50,
    }),
    expected: {
      q: 'release',
      repo: 'repo',
      tags: 'decision',
      meeting_only: 'true',
      sort: 'created_at_asc',
      limit: '25',
      offset: '50',
    },
    query: 'release',
  },
  {
    title: 'Meetings',
    path: '/meetings',
    api: '/api/meetings',
    queryLabel: 'Search meetings',
    cookie: mergeViewCookie('', 'meetings', {
      ...defaultView('meetings'),
      q: 'planning',
      labels: 'release',
      sort: 'title',
      limit: 25,
      offset: 50,
    }),
    expected: {
      q: 'planning',
      labels: 'release',
      sort: 'title',
      limit: '25',
      offset: '50',
    },
    query: 'planning',
  },
  {
    title: 'Vocabulary',
    path: '/meetings?tab=vocabulary',
    api: '/api/meetings/vocabulary',
    queryLabel: 'Search vocabulary',
    cookie: mergeViewCookie('', 'vocabulary', {
      ...defaultView('vocabulary'),
      q: 'term',
      definition: 'defined',
      sort: 'updated',
      limit: 25,
      offset: 50,
    }),
    expected: {
      q: 'term',
      definition: 'defined',
      sort: 'updated',
      limit: '25',
      offset: '50',
    },
    query: 'term',
  },
];

for (const view of cases) {
  test(`${view.title} restores its cookie before requesting data and retains it on reload`, async ({
    page,
    context,
    fixtureAPI,
    baseURL,
  }) => {
    if (!baseURL)
      throw new Error('Preference browser tests require the owned preview');
    fixtureAPI.get(view.api, { items: [], total: 100 });
    for (const fixture of view.fixtures ?? [])
      fixtureAPI.get(fixture.path, fixture.body);
    if (view.counts) fixtureAPI.get(view.counts.path, view.counts.body);
    const encoded = view.cookie
      .slice(VIEW_COOKIE_NAME.length + 1)
      .split(';')[0];
    await context.addCookies([
      { name: VIEW_COOKIE_NAME, value: encoded, url: baseURL, sameSite: 'Lax' },
    ]);
    const target = new URL(view.path, baseURL);
    target.searchParams.set('keep', '1');
    await page.goto(target.href);
    await expect(
      page.getByLabel(view.queryLabel ?? 'Search', { exact: true }),
    ).toHaveValue(view.query);
    const requests = () =>
      fixtureAPI.requests.filter(
        (request) => new URL(request.url).pathname === view.api,
      );
    await expect.poll(() => requests().length).toBe(1);
    expect(Object.fromEntries(new URL(requests()[0].url).searchParams)).toEqual(
      view.expected,
    );
    await page.reload();
    await expect.poll(() => requests().length).toBe(2);
    expect(Object.fromEntries(new URL(requests()[1].url).searchParams)).toEqual(
      view.expected,
    );
    await expect(
      page.getByRole('button', { name: 'Reset view', exact: true }),
    ).toHaveCount(0);
  });
}

test('Memory sequential typing preserves the full applied search and independent list sorting', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/memory/list', { items: [], total: 0 });
  fixtureAPI.get('/api/memory/search', { items: [], total: 0 });
  await page.goto('/memory');
  const input = page.getByRole('textbox', {
    name: 'Search memories',
    exact: true,
  });
  await page
    .getByRole('combobox', { name: 'Sort', exact: true })
    .selectOption('updated_at_asc');
  await input.pressSequentially('release details', { delay: 10 });
  await expect(input).toHaveValue('release details');
  const searches = () =>
    fixtureAPI.requests.filter(
      (request) => new URL(request.url).pathname === '/api/memory/search',
    );
  await expect
    .poll(() =>
      searches().at(-1)
        ? new URL(searches().at(-1)!.url).searchParams.get('q')
        : null,
    )
    .toBe('release details');
  await page.reload();
  await expect(input).toHaveValue('release details');
  await page.getByRole('button', { name: 'Clear', exact: true }).click();
  await expect(
    page.getByRole('combobox', { name: 'Sort', exact: true }),
  ).toHaveValue('updated_at_asc');
  const lists = () =>
    fixtureAPI.requests.filter(
      (request) => new URL(request.url).pathname === '/api/memory/list',
    );
  await expect
    .poll(() => new URL(lists().at(-1)!.url).searchParams.get('sort'))
    .toBe('updated_at_asc');
});

test('Meeting tab links restore their own saved query and page without sharing criteria', async ({
  page,
  context,
  fixtureAPI,
  baseURL,
}) => {
  if (!baseURL)
    throw new Error('Preference browser tests require the owned preview');
  fixtureAPI.get('/api/meetings', { items: [], total: 100 });
  fixtureAPI.get('/api/meetings/vocabulary', { items: [], total: 100 });
  let cookie = mergeViewCookie('', 'meetings', {
    ...defaultView('meetings'),
    q: 'meeting query',
    sort: 'title',
    limit: 25,
    offset: 50,
  });
  cookie = mergeViewCookie(cookie, 'vocabulary', {
    ...defaultView('vocabulary'),
    q: 'vocabulary query',
    sort: 'updated',
    limit: 50,
    offset: 50,
  });
  await context.addCookies([
    {
      name: VIEW_COOKIE_NAME,
      value: cookie.slice(VIEW_COOKIE_NAME.length + 1).split(';')[0],
      url: baseURL,
      sameSite: 'Lax',
    },
  ]);
  await page.goto('/meetings?keep=1');
  await expect(
    page.getByRole('textbox', { name: 'Search meetings' }),
  ).toHaveValue('meeting query');
  await page
    .getByRole('navigation', { name: 'Meeting views' })
    .getByRole('link', { name: 'Vocabulary', exact: true })
    .click();
  await expect(
    page.getByRole('textbox', { name: 'Search vocabulary' }),
  ).toHaveValue('vocabulary query');
  const vocab = () =>
    fixtureAPI.requests.filter(
      (request) => new URL(request.url).pathname === '/api/meetings/vocabulary',
    );
  await expect.poll(() => vocab().length).toBe(1);
  expect(new URL(vocab()[0].url).searchParams.get('offset')).toBe('50');
  await page
    .getByRole('combobox', { name: 'Sort vocabulary' })
    .selectOption('term');
  await page
    .getByRole('navigation', { name: 'Meeting views' })
    .getByRole('link', { name: 'Meetings', exact: true })
    .click();
  await expect(
    page.getByRole('textbox', { name: 'Search meetings' }),
  ).toHaveValue('meeting query');
  await expect(
    page.getByRole('columnheader', { name: 'Title', exact: true }),
  ).toHaveAttribute('aria-sort', 'ascending');
  const meetings = () =>
    fixtureAPI.requests.filter(
      (request) => new URL(request.url).pathname === '/api/meetings',
    );
  await expect.poll(() => meetings().length).toBe(2);
  expect(new URL(meetings()[1].url).searchParams.get('offset')).toBe('50');
  expect(new URL(page.url()).searchParams.get('keep')).toBe('1');
});

test.beforeEach(async ({ fixtureAPI }) => {
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
});
