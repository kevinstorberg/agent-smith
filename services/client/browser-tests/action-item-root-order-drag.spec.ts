import { test, expect, type APIRequest } from './fixtures';
import type { ActionItemQueueRoot, ActionItemQueueMove } from '../src/api';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import {
  epicGroup,
  queuePage,
} from '../src/pages/__tests__/actionItemEpicFixture';
import { enlargeComputedText } from './typography';

for (const scale of [1, 2] as const) {
  for (const scenario of [
    {
      name: 'after an Epic across hidden roots',
      hidden: true,
      source: 4,
      target: 'epic:10',
      edge: 'after',
    },
    {
      name: 'before an Epic across hidden roots',
      hidden: true,
      source: 4,
      target: 'epic:20',
      edge: 'before',
    },
    {
      name: 'before a whole Epic',
      hidden: false,
      source: 4,
      target: 'epic:10',
      edge: 'before',
    },
    {
      name: 'before a root task',
      hidden: false,
      source: 1,
      target: 'item:4',
      edge: 'before',
    },
    {
      name: 'after a root task',
      hidden: false,
      source: 1,
      target: 'item:4',
      edge: 'after',
    },
  ] as const) {
    test(`pointer ordering ${scenario.name} sends the exact captured anchor at ${scale}x text`, async ({
      page,
      fixtureAPI,
    }, testInfo) => {
      const first = queuePage({ items: [actionItem(1)], total: 1 }).items[0];
      const source = queuePage({ items: [actionItem(4)], total: 1 }).items[0];
      const delivery = epicGroup(10, [actionItem(2)]);
      delivery.epic.title = 'Delivery';
      const readiness = epicGroup(20, [actionItem(3)]);
      readiness.epic.title = 'Readiness';
      delivery.epic.position = scenario.hidden ? 1 : 2;
      readiness.epic.position = 10;
      let roots: ActionItemQueueRoot[] = scenario.hidden
        ? [delivery, source, readiness]
        : [first, delivery, source];
      const writes: ActionItemQueueMove[] = [];
      fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
      fixtureAPI.get('/api/action-items/queue', () => ({
        items: roots,
        total: 3,
        matching_count: 3,
      }));
      fixtureAPI.mock(
        'POST',
        '/api/action-items/queue/move',
        ({ request }: APIRequest) => {
          const body = request.postDataJSON() as ActionItemQueueMove;
          writes.push(body);
          expect(body.source).toEqual({
            kind: 'item',
            id: scenario.source,
            expected_revision: 1,
          });
          const [kind, id] = scenario.target.split(':');
          const expected =
            kind === 'epic'
              ? {
                  kind,
                  id: Number(id),
                  expected_revision: 3,
                  cohort: `cohort-${id}`,
                }
              : { kind, id: Number(id), expected_revision: 1 };
          expect(body).toEqual({
            source: { kind: 'item', id: scenario.source, expected_revision: 1 },
            [scenario.edge]: expected,
          });
          const identity = (entry: ActionItemQueueRoot) =>
            entry.kind === 'epic'
              ? `epic:${entry.epic.id}`
              : `item:${entry.item.id}`;
          const moved = roots.find(
            (entry) => identity(entry) === `item:${scenario.source}`,
          )!;
          roots = roots.filter((entry) => entry !== moved);
          const anchor = roots.findIndex(
            (entry) => identity(entry) === scenario.target,
          );
          roots.splice(anchor + (scenario.edge === 'after' ? 1 : 0), 0, moved);
          return { saved: true };
        },
      );
      await page.goto(
        scenario.hidden ? '/action-items?q=visible' : '/action-items',
      );
      const handle = page.getByRole('button', {
        name: `Reorder Task ${scenario.source}`,
        exact: true,
      });
      await expect(handle).toBeEnabled();
      if (scale === 2)
        await enlargeComputedText(page, 2, { preserveMotion: true });
      await handle.scrollIntoViewIfNeeded();
      const start = (await handle.boundingBox())!;
      await page.mouse.move(
        start.x + start.width / 2,
        start.y + start.height / 2,
      );
      await page.mouse.down();
      await page.mouse.move(
        start.x + start.width / 2,
        start.y + start.height / 2 + 10,
        { steps: 4 },
      );
      const target = page.locator(
        `[data-root-order-id="${scenario.target}"][data-root-order-edge="${scenario.edge}"]`,
      );
      await expect(target).toHaveAttribute('data-active', 'true');
      await target.evaluate((element) =>
        element.scrollIntoView({ block: 'center', inline: 'nearest' }),
      );
      const bounds = (await target.boundingBox())!;
      expect(bounds.height).toBeGreaterThanOrEqual(10);
      const point = {
        x: bounds.x + bounds.width / 2,
        y: bounds.y + bounds.height / 2,
      };
      const interiors = await page
        .locator('.action-item-epic-group')
        .evaluateAll((elements) =>
          elements.map((element) => {
            const box = element.getBoundingClientRect();
            return { top: box.top, bottom: box.bottom };
          }),
        );
      expect(
        interiors.some((box) => point.y >= box.top && point.y < box.bottom),
      ).toBe(false);
      await page.mouse.move(point.x, point.y, { steps: 20 });
      await expect(target).toHaveAttribute('data-selected', 'true');
      await expect(
        page.locator('.action-item-epic-group[data-drop-selected="true"]'),
      ).toHaveCount(0);
      await page.screenshot({
        path: testInfo.outputPath('root-ordering-zone.png'),
        fullPage: false,
      });
      await page.mouse.up();
      await expect.poll(() => writes.length).toBe(1);
      const visible = roots.map((entry) =>
        entry.kind === 'epic'
          ? `epic:${entry.epic.id}`
          : `item:${entry.item.id}`,
      );
      await expect
        .poll(() =>
          page
            .locator(
              '.action-item-grouped-table > tbody > tr[data-rfd-draggable-id]',
            )
            .evaluateAll((rows) =>
              rows.map((row) => row.getAttribute('data-rfd-draggable-id')),
            ),
        )
        .toEqual(visible);
      if (scenario.hidden)
        expect(visible).toEqual(['epic:10', 'item:4', 'epic:20']);
      expect(writes).toHaveLength(1);
    });
  }
}
