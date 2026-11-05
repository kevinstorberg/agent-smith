import { test, expect } from './fixtures';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import type { Page } from '@playwright/test';

async function freezeClock(page: Page) {
  await page.clock.install({ time: new Date('2026-11-05T12:00:00Z') });
  await page.clock.pauseAt(new Date('2026-11-05T12:00:01Z'));
}

interface PollingView {
  name: string;
  path: string;
  endpoint: string;
  related?: [string, unknown][];
  responseDelayMs?: number;
}

const views: PollingView[] = [
  ...[
    ['rule', 'rules'],
    ['skill', 'skills'],
    ['tool', 'tools'],
    ['hook', 'hooks'],
    ['agent', 'agents'],
  ].map(([kind, plural]) => ({
    name: plural,
    path: `/harness/${plural}?name=review&project=work&limit=25&offset=50`,
    endpoint: `/api/harness/items/${kind}`,
  })),
  {
    name: 'action items',
    path: '/action-items?q=review&project=work&limit=25&offset=50',
    endpoint: '/api/action-items',
  },
  {
    name: 'memory list',
    path: '/memory?repo=work&limit=25&offset=50',
    endpoint: '/api/memory/list',
  },
  {
    name: 'memory search',
    path: '/memory?q=review&repo=work&limit=25&offset=50',
    endpoint: '/api/memory/search',
  },
  {
    name: 'meetings',
    path: '/meetings?q=review&limit=25&offset=50',
    endpoint: '/api/meetings',
  },
  {
    name: 'vocabulary',
    path: '/meetings?tab=vocabulary&q=review&limit=25&offset=50',
    endpoint: '/api/meetings/vocabulary',
  },
  {
    name: 'profiles',
    path: '/profiles?q=review&limit=25&offset=50',
    endpoint: '/api/profiles',
    related: [['/api/jobs/graph/persona', { items: [], total: 0 }]],
  },
  {
    name: 'plans',
    path: '/plans?q=review&limit=25&offset=50',
    endpoint: '/api/plans',
  },
  {
    name: 'jobs',
    path: '/jobs?q=review&limit=25&offset=50',
    endpoint: '/api/jobs',
  },
  {
    name: 'proposals',
    path: '/proposals?q=review&limit=25&offset=50',
    endpoint: '/api/proposals',
    related: [['/api/proposals/counts', {}]],
  },
  {
    name: 'audit',
    path: '/audit?q=review&limit=25&offset=50',
    endpoint: '/api/audit/events',
    related: [['/api/audit/counts', {}]],
  },
  {
    name: 'eval suites',
    path: '/eval-configs?q=review&limit=25&offset=50',
    endpoint: '/api/eval-configs/suites',
  },
  {
    name: 'Results',
    path: '/evals?q=review&limit=25&offset=50',
    endpoint: '/api/evals',
    related: [
      ['/api/evals/categories', ['rules']],
      ['/api/evals/subcategories', []],
      ['/api/evals/facets', { scenarios: [], models: [] }],
      ['/api/evals/chart/average', []],
    ],
  },
];

const scenarios: PollingView[] = views.flatMap((view) =>
  view.name === 'jobs'
    ? [
        view,
        { ...view, name: 'jobs with delayed responses', responseDelayMs: 250 },
      ]
    : [view],
);

for (const view of scenarios) {
  test(`${view.name} polls its current page four times per visible minute without writes`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    let responseIndex = 0;
    fixtureAPI.get(view.endpoint, async () => {
      const total = 100 + responseIndex++;
      if (view.responseDelayMs) {
        await new Promise((resolve) =>
          setTimeout(resolve, view.responseDelayMs),
        );
      }
      return { items: [], total };
    });
    for (const [path, body] of view.related ?? []) fixtureAPI.get(path, body);
    await freezeClock(page);
    await page.goto(view.path);
    const reads = () =>
      fixtureAPI.requests.filter(
        (request) =>
          request.disposition === 'fixture' &&
          new URL(request.url).pathname === view.endpoint,
      );
    await expect.poll(() => reads().length).toBe(1);
    await expect(page.getByText('Showing 51–75 of 100')).toBeVisible();
    const original = new URL(reads()[0].url).search;
    for (let cycle = 1; cycle <= 4; cycle += 1) {
      await page.clock.runFor(14_999);
      expect(reads()).toHaveLength(cycle);
      const response = page.waitForResponse(
        (result) =>
          new URL(result.url()).pathname === view.endpoint &&
          result.request().method() === 'GET',
      );
      await page.clock.runFor(1);
      await expect.poll(() => reads().length).toBe(cycle + 1);
      expect(await (await response).finished()).toBeNull();
      await expect(
        page.getByText(`Showing 51–75 of ${100 + cycle}`),
      ).toBeVisible();
    }
    expect(
      reads().every((request) => new URL(request.url).search === original),
    ).toBe(true);
    for (const [path] of view.related ?? []) {
      await expect
        .poll(
          () =>
            fixtureAPI.requests.filter(
              (request) => new URL(request.url).pathname === path,
            ).length,
        )
        .toBe(5);
    }
    expect(
      fixtureAPI.requests
        .filter((request) => request.disposition === 'fixture')
        .every((request) => request.method === 'GET'),
    ).toBe(true);
    await testInfo.attach('polling-load.json', {
      contentType: 'application/json',
      body: JSON.stringify({
        view: view.name,
        intervalMs: 15_000,
        scheduledReadsPerMinute: 4 * (1 + (view.related?.length ?? 0)),
      }),
    });
  });
}

test('Action items display agent updates, pause while hidden, and stop polling after navigation', async ({
  page,
  fixtureAPI,
}) => {
  let title = 'Original action item';
  fixtureAPI.get('/api/action-items', () => ({
    items: [actionItem(1, { title })],
    total: 1,
  }));
  fixtureAPI.get('/api/plans', { items: [], total: 0 });
  await freezeClock(page);
  await page.goto('/action-items');
  await expect(
    page.getByRole('button', { name: title, exact: true }),
  ).toBeVisible();
  const reads = () =>
    fixtureAPI.requests.filter(
      (request) => new URL(request.url).pathname === '/api/action-items',
    ).length;
  title = 'Updated by an agent';
  await page.clock.runFor(15_000);
  await expect(
    page.getByRole('button', { name: title, exact: true }),
  ).toBeVisible();
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: true,
    });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  const before = reads();
  await page.clock.runFor(60_000);
  expect(reads()).toBe(before);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: false,
    });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.runFor(15_000);
  await expect.poll(reads).toBe(before + 1);
  await page.goto('/plans');
  await expect(page.getByRole('heading', { name: 'Plans' })).toBeVisible();
  await page.clock.runFor(30_000);
  expect(reads()).toBe(before + 1);
});

test('Chat retains its two-second visible polling interval', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/chat', { items: [], total: 0 });
  fixtureAPI.get('/api/chat/config', { participants: [] });
  await freezeClock(page);
  await page.goto('/chat');
  const reads = () =>
    fixtureAPI.requests.filter(
      (request) => new URL(request.url).pathname === '/api/chat',
    ).length;
  await expect.poll(reads).toBe(1);
  await page.clock.runFor(1_999);
  expect(reads()).toBe(1);
  await page.clock.runFor(1);
  await expect.poll(reads).toBe(2);
});

test.beforeEach(async ({ fixtureAPI }) => {
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
});
