import { test, expect, type APIRequest } from './fixtures';
import { actionItem, deferred } from '../src/pages/__tests__/actionItemFixture';
import { epicGroup } from '../src/pages/__tests__/actionItemEpicFixture';
import { enlargeComputedText } from './typography';
import { expectDialogContained } from './geometry';

for (const scale of [1, 2] as const) {
  for (const input of ['pointer', 'touch', 'keyboard'] as const) {
    const outcomes =
      input === 'pointer'
        ? (['saved', 'lost reply', 'cancel', 'late pointer'] as const)
        : (['saved', 'lost reply', 'cancel'] as const);
    for (const outcome of outcomes) {
      test(`${input} Epic release remains exact through ${outcome} at ${scale}x text`, async ({
        page,
        fixtureAPI,
      }, info) => {
        const task = actionItem(1, {
          title: 'Preserve the complete delivery checklist and partner handoff',
          due_at: '2026-12-01T14:00:00Z',
        });
        const source = epicGroup(10, [task]);
        source.epic.title = 'Delivery';
        const target = epicGroup(20, [actionItem(2)]);
        target.epic.title = 'Customer readiness';
        const other = epicGroup(30, [actionItem(3)]);
        other.epic.title = 'Security review';
        const roots = [source, target, other];
        const expectedBody = {
          expected_revision: task.revision,
          expected_parent: {
            id: 10,
            expected_revision: source.epic.revision,
            cohort: source.epic.cohort,
          },
          destination: {
            id: 20,
            expected_revision: target.epic.revision,
            cohort: target.epic.cohort,
          },
        };
        const bodies: unknown[] = [];
        const save = deferred<void>();
        const refresh = deferred<void>();
        let refreshing = false;
        fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
        fixtureAPI.get('/api/action-items/queue', async () => {
          if (bodies.length) {
            refreshing = true;
            await refresh.promise;
          }
          return { items: roots, total: 3, matching_count: 3 };
        });
        fixtureAPI.mock(
          'POST',
          '/api/action-items/1/epic',
          async ({ request }: APIRequest) => {
            bodies.push(request.postDataJSON());
            await save.promise;
            const entry = source.children.shift()!;
            target.children.push({
              ...entry,
              parent_epic_id: 20,
              position: 2,
              item: { ...task, revision: task.revision + 1 },
            });
            return outcome === 'lost reply'
              ? {
                  detail:
                    'The save response was lost. Review the current list.',
                }
              : task;
          },
          outcome === 'lost reply' ? 504 : 200,
        );
        await page.goto('/action-items');
        const handle = page.getByRole('button', {
          name: `Reorder ${task.title}`,
          exact: true,
        });
        await expect(handle).toBeEnabled();
        if (scale === 2)
          await enlargeComputedText(page, 2, { preserveMotion: true });
        if (outcome === 'late pointer')
          await page.addStyleTag({
            // Keep a real SDK transition open while native input and scrolling intervene.
            content: '.action-item-row { transition-duration: 1s !important; }',
          });
        await page.evaluate(() => {
          Object.assign(window, { epicDropDurations: [] });
          document.addEventListener(
            'transitionrun',
            (event) => {
              const transition = event as TransitionEvent;
              const row = transition.target as HTMLElement;
              if (
                transition.propertyName === 'transform' &&
                row.dataset.rfdDraggableId === 'item:1' &&
                row.style.zIndex === '4500'
              )
                (
                  window as unknown as { epicDropDurations: string[] }
                ).epicDropDurations.push(
                  getComputedStyle(row).transitionDuration,
                );
            },
            true,
          );
        });
        const cdp =
          input === 'touch' ? await page.context().newCDPSession(page) : null;
        try {
          if (input === 'keyboard') {
            await handle.focus();
            await page.keyboard.press('Space');
            await expect(
              page.locator('.action-item-grouped-container'),
            ).toHaveAttribute('data-dragging', 'true');
            await page.keyboard.press('Shift+ArrowRight');
            await page.keyboard.press('Shift+ArrowRight');
          } else {
            await handle.evaluate((element) =>
              element.scrollIntoView({
                behavior: 'instant',
                block: 'center',
                inline: 'nearest',
              }),
            );
            const box = (await handle.boundingBox())!;
            const from = {
              x: box.x + box.width / 2,
              y: box.y + box.height / 2,
            };
            if (cdp) {
              await cdp.send('Emulation.setTouchEmulationEnabled', {
                enabled: true,
              });
              await cdp.send('Input.dispatchTouchEvent', {
                type: 'touchStart',
                touchPoints: [{ ...from, id: 1 }],
              });
            } else {
              await page.mouse.move(from.x, from.y);
              await page.mouse.down();
              await page.mouse.move(from.x, from.y + 10, { steps: 4 });
            }
            await expect(
              page.locator('.action-item-grouped-container'),
            ).toHaveAttribute('data-dragging', 'true');
            const destination = page.locator('[data-epic-drop-target="20"]');
            await destination.evaluate((element) =>
              element.scrollIntoView({
                behavior: 'instant',
                block: 'center',
                inline: 'nearest',
              }),
            );
            const bounds = (await destination.boundingBox())!;
            const point = {
              x: bounds.x + bounds.width / 2,
              y: Math.max(80, Math.min(780, bounds.y + bounds.height / 2)),
            };
            if (cdp)
              await cdp.send('Input.dispatchTouchEvent', {
                type: 'touchMove',
                touchPoints: [{ ...point, id: 1 }],
              });
            else await page.mouse.move(point.x, point.y, { steps: 20 });
          }
          await expect(
            page.locator('[data-epic-drop-target="20"]'),
          ).toHaveAttribute('data-drop-selected', 'true');
          if (outcome === 'cancel') {
            await page.keyboard.press('Escape');
            await expect(
              page.locator('.action-item-grouped-container'),
            ).toHaveAttribute('data-dragging', 'false');
            if (cdp)
              await cdp.send('Input.dispatchTouchEvent', {
                type: 'touchEnd',
                touchPoints: [],
              });
            else if (input === 'pointer') await page.mouse.up();
            expect(bodies).toEqual([]);
            await expect(page.locator('.action-item-pending-move')).toHaveCount(
              0,
            );
            return;
          }
          if (cdp)
            await cdp.send('Input.dispatchTouchEvent', {
              type: 'touchEnd',
              touchPoints: [],
            });
          else if (input === 'keyboard') await page.keyboard.press('Space');
          else await page.mouse.up();
          if (outcome === 'late pointer') {
            const row = page.locator('[data-rfd-draggable-id="item:1"]');
            await expect(row).toHaveCSS('z-index', '4500');
            const outside = (await page
              .locator('[data-epic-drop-target="none"]')
              .boundingBox())!;
            await page.mouse.move(
              outside.x + outside.width / 2,
              outside.y + outside.height / 2,
            );
            expect(bodies).toEqual([]);
            await page.evaluate(() => window.scrollBy(0, 80));
            await expect.poll(() => bodies.length).toBe(1);
            expect(bodies).toEqual([expectedBody]);
          }
          const pending = page.locator('.action-item-pending-move');
          await expect(pending).toBeVisible();
          await expect(pending).toHaveText('Moving to Customer readiness…');
          await expect(
            page.getByRole('status').filter({ hasText: task.title }),
          ).toHaveText(`Moving ${task.title} to Customer readiness…`);
          await expectDialogContained(pending);
          await expect.poll(() => bodies.length).toBe(1);
          await page.mouse.move(20, 20);
          await page.evaluate(() => window.scrollBy(0, 80));
          await expect(pending).toHaveText('Moving to Customer readiness…');
          await expect(
            page.getByRole('button', { name: 'More filters' }),
          ).toBeDisabled();
          expect(bodies).toEqual([expectedBody]);
          const durations = await page.evaluate(
            () =>
              (window as unknown as { epicDropDurations: string[] })
                .epicDropDurations,
          );
          // A keyboard drop at its SDK home can complete without any animation.
          if (input !== 'keyboard') expect(durations.length).toBeGreaterThan(0);
          expect(
            durations.every((value) =>
              value
                .split(',')
                .every(
                  (part) =>
                    part.trim() ===
                    (outcome === 'late pointer' ? '1s' : '0.001s'),
                ),
            ),
          ).toBe(true);
          await page.screenshot({
            path: info.outputPath(`pending-${input}-${scale}x.png`),
            fullPage: false,
          });
          save.resolve();
          await expect.poll(() => refreshing).toBe(true);
          await expect(pending).toBeVisible();
          await expect(
            page.getByRole('button', { name: 'More filters' }),
          ).toBeDisabled();
          refresh.resolve();
          await expect(pending).toHaveCount(0);
          await expect(
            page.locator('[data-epic-drop-target="20"]').getByRole('button', {
              name: task.title,
              exact: true,
            }),
          ).toBeVisible();
          await expect(
            page.getByRole('button', { name: 'More filters' }),
          ).toBeEnabled();
          if (outcome === 'lost reply')
            await expect(page.getByRole('alert')).toContainText(
              'save response was lost',
            );
          expect(bodies).toHaveLength(1);
          expect(target.children.map((entry) => entry.item.id)).toEqual([2, 1]);
        } finally {
          save.resolve();
          refresh.resolve();
          await cdp?.detach();
        }
      });
    }
  }
}
