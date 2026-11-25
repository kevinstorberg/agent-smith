import { test, expect, type APIRequest } from './fixtures';
import type { ActionItemEpicCreate, ActionItemQueueRoot } from '../src/api';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import {
  epicGroup,
  queuePage,
} from '../src/pages/__tests__/actionItemEpicFixture';
import { openItemActions } from './actionItemDisclosures';
import {
  expectControlReachable,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { enlargeComputedText } from './typography';

for (const location of ['root', 'child'] as const) {
  for (const status of ['open', 'completed'] as const) {
    for (const doubled of [false, true]) {
      test(`direct Epic creation preserves a ${location} ${status} task at ${doubled ? 'double' : 'normal'} text`, async ({
        page,
        fixtureAPI,
      }, testInfo) => {
        const item = actionItem(2, {
          title: 'Coordinate the clinical integration rollout',
          description:
            'Keep the existing task details and the delivery checklist.',
          project: 'Work',
          tags: ['delivery', 'clinical'],
          due_at: '2026-12-01T14:00:00Z',
          status,
          revision: 7,
          priority: status === 'open' ? 1 : null,
        });
        const original = epicGroup(10, [item]);
        let roots: ActionItemQueueRoot[] =
          location === 'child'
            ? [original]
            : queuePage({ items: [item], total: 1 }).items;
        const writes: ActionItemEpicCreate[] = [];
        let catalogReads = 0;
        fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
        fixtureAPI.get('/api/action-items/queue', () => ({
          items: roots,
          total: roots.length,
          matching_count: 1,
        }));
        fixtureAPI.get('/api/action-items/epics', () => {
          catalogReads++;
          return { items: [original.epic] };
        });
        fixtureAPI.mock(
          'POST',
          '/api/action-items/epics',
          ({ request }: APIRequest) => {
            const body: ActionItemEpicCreate = request.postDataJSON();
            writes.push(body);
            expect(body).toEqual({
              title: item.title,
              request_id: expect.stringMatching(
                /^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/,
              ),
              item_id: item.id,
              membership: {
                expected_revision: item.revision,
                expected_parent:
                  location === 'child'
                    ? { id: 10, expected_revision: 3, cohort: 'cohort-10' }
                    : null,
              },
            });
            const created = epicGroup(11, [
              { ...item, revision: item.revision + 1 },
            ]);
            created.epic.title = body.title;
            roots =
              location === 'child'
                ? [
                    {
                      ...original,
                      children: [],
                      matching_count: 0,
                      total_count: 0,
                    },
                    created,
                  ]
                : [created];
            return created.epic;
          },
        );
        await page.goto('/action-items?status=all');
        await openItemActions(page, item.title);
        await page
          .getByRole('button', {
            name: 'Create Epic from this item',
            exact: true,
          })
          .click();
        const name = page.getByRole('textbox', {
          name: 'Epic name',
          exact: true,
        });
        await expect(name).toHaveValue(item.title);
        if (doubled) await enlargeComputedText(page);
        const save = page.getByRole('button', {
          name: 'Save Epic',
          exact: true,
        });
        await expectControlReachable(name);
        await expectControlReachable(save);
        await expectDocumentContained(page);
        await expectMainContained(page);
        await page.screenshot({
          path: testInfo.outputPath('direct-create-form.png'),
          fullPage: true,
        });
        await save.click();
        await expect.poll(() => writes.length).toBe(1);
        await expect(name).toHaveCount(0);
        const group = page.getByRole('region', {
          name: `Epic ${item.title}`,
          exact: true,
        });
        await expect(
          group.getByRole('button', { name: item.title, exact: true }),
        ).toHaveCount(2);
        const saved = roots.find(
          (root) => root.kind === 'epic' && root.epic.id === 11,
        );
        expect(saved?.kind).toBe('epic');
        if (saved?.kind !== 'epic')
          throw new Error('Created Epic missing from canonical queue');
        expect(saved.children).toHaveLength(1);
        expect({ ...saved.children[0].item, revision: item.revision }).toEqual(
          item,
        );
        expect(saved.children[0].parent_epic_id).toBe(11);
        expect(catalogReads).toBe(0);
        expect(writes).toHaveLength(1);
      });
    }
  }
}

for (const location of ['root', 'child'] as const) {
  for (const finish of ['retry', 'cancel'] as const) {
    test(`an applied-but-lost ${location} Epic creation retains its receipt for explicit ${finish}`, async ({
      page,
      fixtureAPI,
    }) => {
      const item = actionItem(2, {
        title: 'Keep the original task and delivery details',
        revision: 7,
        description: 'Preserve this task after the response is lost.',
        project: 'Work',
        tags: ['delivery', 'clinical'],
        due_at: '2026-12-01T14:00:00Z',
      });
      const previous = epicGroup(10, [item]);
      const created = epicGroup(12, [{ ...item, revision: 8 }]);
      created.epic.title = item.title;
      let roots: ActionItemQueueRoot[] =
        location === 'root'
          ? queuePage({ items: [item], total: 1 }).items
          : [previous];
      const writes: ActionItemEpicCreate[] = [];
      fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
      fixtureAPI.get('/api/action-items/queue', () => ({
        items: roots,
        total: roots.length,
        matching_count: 1,
      }));
      fixtureAPI.mock(
        'POST',
        '/api/action-items/epics',
        ({ request }: APIRequest) => {
          writes.push(request.postDataJSON());
          roots =
            location === 'root'
              ? [created]
              : [
                  {
                    ...previous,
                    children: [],
                    matching_count: 0,
                    total_count: 0,
                  },
                  created,
                ];
          fixtureAPI.mock(
            'POST',
            '/api/action-items/epics',
            ({ request }: APIRequest) => {
              writes.push(request.postDataJSON());
              expect(writes[1]).toEqual(writes[0]);
              return created.epic;
            },
          );
          return {
            detail: 'Creation response was lost after the server applied it',
          };
        },
        504,
      );

      await page.goto('/action-items?status=all');
      await openItemActions(page, item.title);
      await page
        .getByRole('button', {
          name: 'Create Epic from this item',
          exact: true,
        })
        .click();
      await page
        .getByRole('button', { name: 'Save Epic', exact: true })
        .click();
      const recovery = page.getByRole('group', {
        name: 'Unfinished Epic creation',
      });
      await expect(recovery).toBeVisible();
      await expect(
        page.getByRole('textbox', { name: 'Epic name', exact: true }),
      ).toHaveCount(0);
      expect(writes).toHaveLength(1);
      expect(writes[0]).toEqual({
        title: item.title,
        request_id: expect.any(String),
        item_id: item.id,
        membership: {
          expected_revision: 7,
          expected_parent:
            location === 'root'
              ? null
              : { id: 10, expected_revision: 3, cohort: 'cohort-10' },
        },
      });
      await expect(
        page.getByRole('button', { name: 'New Epic', exact: true }),
      ).toBeDisabled();
      await expect(
        page.getByRole('button', {
          name: `Move ${item.title} to project`,
          exact: true,
        }),
      ).toBeDisabled();
      await expectControlReachable(
        recovery.getByRole('button', { name: 'Retry', exact: true }),
      );
      await expectControlReachable(
        recovery.getByRole('button', { name: 'Cancel retry' }),
      );
      await expectDocumentContained(page);
      await expectMainContained(page);

      if (finish === 'retry') {
        await recovery
          .getByRole('button', { name: 'Retry', exact: true })
          .click();
        await expect(recovery).toHaveCount(0);
        expect(writes).toHaveLength(2);
        expect(writes[1]).toEqual(writes[0]);
      } else {
        await recovery.getByRole('button', { name: 'Cancel retry' }).click();
        await expect(recovery).toHaveCount(0);
        expect(writes).toHaveLength(1);
      }
      await expect(
        page.getByRole('button', { name: 'New Epic', exact: true }),
      ).toBeEnabled();
      expect({ ...created.children[0].item, revision: item.revision }).toEqual(
        item,
      );
      expect(
        roots.find(
          (root) => root.kind === 'epic' && root.epic.id === created.epic.id,
        ),
      ).toEqual(created);
    });
  }
}
