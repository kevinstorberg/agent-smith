import { test, expect, type APIRequest } from './fixtures';
import type {
  ActionItemQueueEntry,
  ActionItemQueueRoot,
  ActionItemEpicReference,
} from '../src/api';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import {
  epicGroup,
  queuePage,
} from '../src/pages/__tests__/actionItemEpicFixture';
import { epicReference } from '../src/utils/actionItemEpics';
import { enlargeComputedText } from './typography';

for (const scale of [1, 2] as const) {
  for (const input of ['keyboard', 'pointer'] as const) {
    for (const scenario of [
      {
        name: 'root into an Epic',
        parent: null,
        destination: 20,
        steps: 2,
        expanded: false,
      },
      {
        name: 'root into an expanded Epic body',
        parent: null,
        destination: 20,
        steps: 2,
        expanded: true,
      },
      {
        name: 'between Epics',
        parent: 10,
        destination: 20,
        steps: 2,
        expanded: false,
      },
      {
        name: 'between expanded Epic bodies',
        parent: 10,
        destination: 20,
        steps: 2,
        expanded: true,
      },
      {
        name: 'out to No Epic',
        parent: 10,
        destination: null,
        steps: 1,
        expanded: false,
      },
    ] as const) {
      test(`${input} drag moves a task ${scenario.name} with one atomic membership write at ${scale}x text`, async ({
        page,
        fixtureAPI,
      }, testInfo) => {
        const item = actionItem(1, {
          title: 'Preserve the delivery checklist',
          due_at: '2026-12-01T14:00:00Z',
        });
        const first = epicGroup(
          10,
          scenario.parent === 10 ? [item, actionItem(2)] : [actionItem(2)],
        );
        first.epic.title = 'Release delivery';
        const second = epicGroup(
          20,
          scenario.expanded ? [actionItem(5), actionItem(6)] : [],
        );
        second.epic.title = 'Customer readiness';
        let roots: ActionItemQueueRoot[] = [
          ...(scenario.parent === null
            ? queuePage({ items: [item], total: 1 }).items
            : []),
          first,
          second,
        ];
        const writes: {
          expected_revision: number;
          expected_parent: ActionItemEpicReference | null;
          destination: ActionItemEpicReference | null;
        }[] = [];
        fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
        fixtureAPI.get('/api/action-items/queue', () => ({
          items: roots,
          total: roots.length,
          matching_count: roots.reduce(
            (count, root) =>
              count + (root.kind === 'item' ? 1 : root.children.length),
            0,
          ),
        }));
        const parent =
          scenario.parent === null ? null : epicReference(first.epic);
        const destination =
          scenario.destination === null ? null : epicReference(second.epic);
        fixtureAPI.mock(
          'POST',
          '/api/action-items/1/epic',
          ({ request }: APIRequest) => {
            const body = request.postDataJSON();
            writes.push(body);
            expect(body).toEqual({
              expected_revision: item.revision,
              expected_parent: parent,
              destination,
            });
            const entry = roots
              .flatMap((root) =>
                root.kind === 'item' ? [root] : root.children,
              )
              .find((child) => child.item.id === item.id)!;
            roots = roots.filter(
              (root) => root.kind !== 'item' || root.item.id !== item.id,
            );
            for (const root of roots)
              if (root.kind === 'epic')
                root.children = root.children.filter(
                  (child) => child.item.id !== item.id,
                );
            const moved: ActionItemQueueEntry = {
              ...entry,
              parent_epic_id: scenario.destination,
              item: { ...entry.item, revision: entry.item.revision + 1 },
              position:
                scenario.destination === null ? 2 : second.children.length + 1,
            };
            if (scenario.destination === null) roots.splice(1, 0, moved);
            else second.children.push(moved);
            return moved.item;
          },
        );
        await page.goto('/action-items');
        await expect(
          page.getByRole('button', { name: item.title, exact: true }),
        ).toBeVisible();
        if (!scenario.expanded)
          await page
            .getByRole('region', {
              name: 'Epic Customer readiness',
              exact: true,
            })
            .getByRole('button', { name: 'Customer readiness', exact: true })
            .click();
        if (scale === 2)
          await enlargeComputedText(page, 2, { preserveMotion: true });
        const handle = page.getByRole('button', {
          name: `Reorder ${item.title}`,
          exact: true,
        });
        await expect(handle).toBeEnabled();
        if (input === 'keyboard') {
          await handle.focus();
          await page.keyboard.press('Space');
        } else {
          await handle.scrollIntoViewIfNeeded();
          const from = (await handle.boundingBox())!;
          await page.mouse.move(
            from.x + from.width / 2,
            from.y + from.height / 2,
          );
          await page.mouse.down();
          await page.mouse.move(
            from.x + from.width / 2,
            from.y + from.height / 2 + 10,
            { steps: 4 },
          );
        }
        await expect(
          page.getByRole('region', { name: 'action items list', exact: true }),
        ).toHaveAttribute('data-dragging', 'true');
        if (input === 'keyboard') {
          for (let step = 0; step < scenario.steps; step++)
            await page.keyboard.press('Shift+ArrowRight');
        } else {
          const container = page.locator(
            `[data-epic-drop-target="${scenario.destination ?? 'none'}"]`,
          );
          const target = scenario.expanded
            ? container.getByRole('button', { name: 'Task 6', exact: true })
            : container;
          await target.evaluate((element) =>
            element.scrollIntoView({ block: 'center', inline: 'nearest' }),
          );
          const bounds = (await target.boundingBox())!;
          await page.mouse.move(
            bounds.x + bounds.width / 2,
            bounds.y + bounds.height / 2,
            { steps: 20 },
          );
          await expect(container).toHaveAttribute('data-drop-selected', 'true');
        }
        const name =
          scenario.destination === null ? 'No Epic' : 'Customer readiness';
        await expect(
          page
            .getByRole('status')
            .filter({ hasText: `Move ${item.title} to ${name}.` }),
        ).toBeVisible();
        await expect(
          page.locator('[id^="rfd-announcement"]'),
        ).not.toContainText('cannot be dropped');
        if (input === 'keyboard')
          await page.screenshot({
            path: testInfo.outputPath(`${input}-epic-target.png`),
            fullPage: false,
          });
        if (input === 'keyboard') await page.keyboard.press('Space');
        else await page.mouse.up();
        await expect(page.locator('[id^="rfd-announcement"]')).toContainText(
          'Checking the current list.',
        );
        await expect.poll(() => writes.length).toBe(1);
        const savedTitle =
          scenario.destination === null
            ? page
                .locator(
                  '.action-item-grouped-table > tbody > tr.action-item-row',
                )
                .getByRole('button', { name: item.title, exact: true })
            : page
                .getByRole('region', {
                  name: 'Epic Customer readiness',
                  exact: true,
                })
                .getByRole('button', { name: item.title, exact: true });
        await expect(savedTitle).toBeVisible();
        const saved = roots
          .flatMap((root) => (root.kind === 'item' ? [root] : root.children))
          .find((entry) => entry.item.id === item.id)!;
        expect(saved.parent_epic_id).toBe(scenario.destination);
        if (scenario.expanded) {
          expect(second.children.map((entry) => entry.item.id)).toEqual([
            5, 6, 1,
          ]);
          expect(saved.position).toBe(3);
        }
        expect({ ...saved.item, revision: item.revision }).toEqual(item);
        expect(writes).toHaveLength(1);
      });
    }
  }
}

for (const input of ['keyboard', 'pointer'] as const) {
  test(`${input} root task ordering still crosses a whole Epic without changing membership`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    const first = actionItem(1);
    const last = actionItem(4);
    let roots: ActionItemQueueRoot[] = [
      queuePage({ items: [first], total: 1 }).items[0],
      epicGroup(10, [actionItem(2)]),
      queuePage({ items: [last], total: 1 }).items[0],
    ];
    const writes: unknown[] = [];
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
        writes.push(request.postDataJSON());
        expect(request.postDataJSON()).toEqual({
          source: { kind: 'item', id: 1, expected_revision: 1 },
          after: { kind: 'item', id: 4, expected_revision: 1 },
        });
        roots = [roots[1], roots[2], roots[0]];
        return { moved: true };
      },
    );
    await page.goto('/action-items');
    const handle = page.getByRole('button', {
      name: 'Reorder Task 1',
      exact: true,
    });
    await expect(handle).toBeEnabled();
    await handle.scrollIntoViewIfNeeded();
    if (input === 'keyboard') {
      await handle.focus();
      await page.keyboard.press('Space');
    } else {
      const box = (await handle.boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(
        box.x + box.width / 2,
        box.y + box.height / 2 + 10,
        { steps: 4 },
      );
    }
    await expect(
      page.getByRole('region', { name: 'action items list', exact: true }),
    ).toHaveAttribute('data-dragging', 'true');
    if (input === 'keyboard') {
      await page.keyboard.press('ArrowDown');
      await page.keyboard.press('ArrowDown');
    } else {
      const edge = page.locator(
        '[data-root-order-id="item:4"][data-root-order-edge="after"]',
      );
      await expect(edge).toHaveAttribute('data-active', 'true');
      await edge.evaluate((element) =>
        element.scrollIntoView({ block: 'center', inline: 'nearest' }),
      );
      const box = (await edge.boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, {
        steps: 20,
      });
      await expect(edge).toHaveAttribute('data-selected', 'true');
    }
    if (input === 'keyboard')
      await expect(page.locator('[id^="rfd-announcement"]')).toContainText(
        'position 1 to position 3',
      );
    else
      await expect(
        page
          .getByRole('status')
          .filter({ hasText: 'Move Task 1 after Task 4' }),
      ).toBeVisible();
    if (input === 'keyboard') await page.keyboard.press('Space');
    else await page.mouse.up();
    if (input === 'pointer')
      await expect(page.locator('[id^="rfd-announcement"]')).toContainText(
        'Move Task 1 after Task 4. Checking the current list.',
      );
    await expect.poll(() => writes.length).toBe(1);
    await expect(
      page.locator(
        '.action-item-grouped-table > tbody > tr[data-rfd-draggable-id]',
      ),
    ).toHaveCount(3);
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
      .toEqual(['epic:10', 'item:4', 'item:1']);
    await page.screenshot({
      path: testInfo.outputPath('root-order-preserved.png'),
      fullPage: true,
    });
    expect(writes).toHaveLength(1);
  });
}
