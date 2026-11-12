import { test, expect, type APIRequest } from './fixtures';
import type { ActionItem, ActionItemMove } from '../src/api';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import {
  expectControlContained,
  expectControlReachable,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { enlargeComputedText } from './typography';

interface QueueFixtureAPI {
  get(path: string, response: unknown): void;
  mock(
    method: 'POST',
    path: string,
    response: (request: APIRequest) => unknown,
  ): void;
}

function queueFixture(fixtureAPI: QueueFixtureAPI, project: string | null) {
  const soon = new Date(Date.now() + 12 * 60 * 60 * 1000).toISOString();
  const later = new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString();
  const initial = Array.from({ length: 25 }, (_, index) => {
    const matching = actionItem(index + 1, {
      project,
      due_at: soon,
      revision: index === 10 ? 7 : 1,
    });
    const mismatch: Partial<ActionItem> =
      index % 4 === 0
        ? { project: 'Other' }
        : index % 4 === 1
          ? { tags: ['unrelated'] }
          : index % 4 === 2
            ? { title: `Hidden ${index}`, description: 'Unrelated' }
            : { due_at: later };
    const hidden = actionItem(index + 1001, {
      project,
      due_at: soon,
      ...mismatch,
    });
    return [hidden, matching];
  }).flat();
  let rows = initial.map((item, index) => ({ ...item, priority: index + 1 }));
  const writes: ActionItemMove[] = [];
  const reads: URL[] = [];
  fixtureAPI.get('/api/action-items/projects', {
    items: ['Work', 'Other'].map((name, index) => ({
      id: index + 1,
      name,
      created_at: '2026-11-01T12:00:00Z',
    })),
    total: 2,
  });
  fixtureAPI.get('/api/action-items', ({ url }: APIRequest) => {
    reads.push(url);
    const params = url.searchParams;
    const query = params.get('q')?.toLowerCase();
    const tags = params.getAll('tags');
    const dueHours = params.get('due_within_hours');
    const matching = rows.filter(
      (item) =>
        (!params.get('project') || item.project === params.get('project')) &&
        (!params.has('unassigned') || item.project === null) &&
        (!query ||
          `${item.title} ${item.description}`.toLowerCase().includes(query)) &&
        tags.every((tag) => item.tags.includes(tag)) &&
        (!dueHours ||
          (item.due_at !== null &&
            item.due_at !== undefined &&
            new Date(item.due_at).getTime() <=
              Date.now() + Number(dueHours) * 60 * 60 * 1000)) &&
        (!params.get('status') ||
          params.get('status') === 'all' ||
          item.status === params.get('status')),
    );
    if (params.get('sort') === 'manual_desc') matching.reverse();
    const offset = Number(params.get('offset') ?? 0);
    const limit = Number(params.get('limit') ?? 10);
    return {
      items: matching.slice(offset, offset + limit),
      total: matching.length,
    };
  });
  fixtureAPI.mock('POST', '/api/action-items/11/move', ({ request }) => {
    const body = request.postDataJSON() as ActionItemMove;
    expect(body.expected_revision).toBe(7);
    writes.push(body);
    const moved = rows.find((item) => item.id === 11)!;
    const remaining = rows.filter((item) => item.id !== moved.id);
    const anchor = remaining.findIndex(
      (item) => item.id === (body.before_id ?? body.after_id),
    );
    expect(anchor).toBeGreaterThanOrEqual(0);
    remaining.splice(anchor + (body.after_id === undefined ? 0 : 1), 0, {
      ...moved,
      revision: moved.revision + 1,
    });
    rows = remaining.map((item, index) => ({ ...item, priority: index + 1 }));
    return rows.find((item) => item.id === moved.id)!;
  });
  return { initial, writes, reads, rows: () => rows };
}

for (const edge of ['top', 'bottom'] as const) {
  test(`moves to the ${edge} of every matching page and restores keyboard focus`, async ({
    page,
    fixtureAPI,
  }) => {
    const project = edge === 'top' ? 'Work' : null;
    const queue = queueFixture(fixtureAPI, project);
    const scope: Record<string, string> = project
      ? { project }
      : { unassigned: 'true' };
    const criteria = new URLSearchParams({
      ...scope,
      status: 'open',
      sort: 'manual',
      q: 'Task',
      tags: 'security',
      due_within_hours: '48',
      limit: '10',
      offset: '10',
    });
    await page.goto(`/action-items?${criteria}`);
    const move = page.getByRole('button', {
      name: `Move Task 11 to ${edge}`,
      exact: true,
    });
    await expect(move).toBeEnabled();
    await expectControlReachable(move);
    await move.focus();
    await page.keyboard.press(edge === 'top' ? 'Enter' : 'Space');
    const expectedMove = {
      expected_revision: 7,
      ...(edge === 'top' ? { before_id: 1 } : { after_id: 25 }),
    };
    await expect.poll(() => queue.writes).toEqual([expectedMove]);
    await expect(move).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: 'Task 12', exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole('region', { name: 'action items list', exact: true }),
    ).toBeFocused();
    const probe = queue.reads.find(
      (url) => url.searchParams.get('limit') === '1',
    );
    expect(probe).toBeDefined();
    expect(Object.fromEntries(probe!.searchParams)).toMatchObject({
      ...scope,
      status: 'open',
      sort: edge === 'top' ? 'manual' : 'manual_desc',
      q: 'Task',
      tags: 'security',
      due_within_hours: '48',
      limit: '1',
      offset: '0',
    });
    expect(Object.fromEntries(new URL(page.url()).searchParams)).toMatchObject({
      ...scope,
      offset: '10',
      sort: 'manual',
      q: 'Task',
      tags: 'security',
      due_within_hours: '48',
    });
    expect(
      queue
        .rows()
        .filter((item) => item.id !== 11)
        .map((item) => item.id),
    ).toEqual(
      queue.initial.filter((item) => item.id !== 11).map((item) => item.id),
    );
    expect(
      queue
        .rows()
        .filter((item) => item.id !== 11)
        .map((item) => item.revision),
    ).toEqual(
      queue.initial
        .filter((item) => item.id !== 11)
        .map((item) => item.revision),
    );
    await page.reload();
    await expect(
      page.getByRole('button', { name: 'Task 12', exact: true }),
    ).toBeVisible();
    await page
      .getByRole('button', {
        name: edge === 'top' ? 'Previous' : 'Next',
        exact: true,
      })
      .click();
    const moved = page.getByRole('button', { name: 'Task 11', exact: true });
    await expect(moved).toBeVisible();
    const displayed = page.locator('.action-item-title');
    await expect(
      edge === 'top' ? displayed.first() : displayed.last(),
    ).toHaveAccessibleName('Task 11');
    await expect(
      page.getByRole('button', {
        name: `Move Task 11 to ${edge}`,
        exact: true,
      }),
    ).toBeDisabled();
    expect(queue.writes).toHaveLength(1);
    await expectDocumentContained(page);
    await expectMainContained(page);
  });
}

test('offers edge movement only for open items in ascending Priority view', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items', ({ url }: APIRequest) => ({
    items: [
      actionItem(1, {
        status:
          url.searchParams.get('status') === 'completed' ? 'completed' : 'open',
      }),
    ],
    total: 1,
  }));
  for (const query of [
    'status=open&sort=title',
    'status=open&sort=manual_desc',
    'status=completed&sort=completed',
  ]) {
    await page.goto(`/action-items?${query}`);
    await expect(
      page.getByRole('button', { name: 'Task 1', exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: /^Move .* to (top|bottom)$/ }),
    ).toHaveCount(0);
  }
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

for (const scale of [1, 2]) {
  test(`keeps move buttons and neighboring actions reachable at ${scale}x text`, async ({
    page,
    fixtureAPI,
  }) => {
    const row = actionItem(2, {
      title:
        'Review the longer action item with project details and supporting context',
    });
    fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
    fixtureAPI.get('/api/action-items', {
      items: [actionItem(1), row, actionItem(3)],
      total: 3,
    });
    await page.goto('/action-items?status=open&sort=manual');
    const top = page.getByRole('button', {
      name: `Move ${row.title} to top`,
      exact: true,
    });
    const bottom = page.getByRole('button', {
      name: `Move ${row.title} to bottom`,
      exact: true,
    });
    await expect(top).toBeEnabled();
    await expect(bottom).toBeEnabled();
    await expect(top).toHaveText('Move to top');
    await expect(bottom).toHaveText('Move to bottom');
    if (scale === 2) await enlargeComputedText(page);
    const actions = top.locator('..');
    const cell = actions.locator('..');
    for (const button of await actions.getByRole('button').all()) {
      await expectControlContained(button, cell);
      await expectControlReachable(button);
      const [bounds, parent] = await Promise.all([
        button.boundingBox(),
        cell.boundingBox(),
      ]);
      expect(bounds!.y).toBeGreaterThanOrEqual(parent!.y - 1);
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(
        parent!.y + parent!.height + 1,
      );
    }
    await expectDocumentContained(page);
    await expectMainContained(page);
  });
}
