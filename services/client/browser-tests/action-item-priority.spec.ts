import { test, expect, type APIRequest } from './fixtures';
import { actionItem, deferred } from '../src/pages/__tests__/actionItemFixture';
import { epicGroup } from '../src/pages/__tests__/actionItemEpicFixture';
import { openItemActions } from './actionItemDisclosures';
import {
  expectControlReachable,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { enlargeComputedText } from './typography';

for (const scale of [1, 2]) {
  test(`Priority planning marks Epic children and filters persistently without reordering at ${scale}x text`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    let saved = actionItem(1, { is_priority: false });
    const sibling = actionItem(2, { is_priority: false });
    const gate = deferred<void>();
    const writes: unknown[] = [];
    fixtureAPI.get('/api/action-items/projects', {
      items: [{ id: 1, name: 'Work', created_at: '2026-11-01T00:00:00Z' }],
      total: 1,
    });
    fixtureAPI.get('/api/action-items/epics', { items: [epicGroup().epic] });
    fixtureAPI.get('/api/action-items/queue', ({ url }: APIRequest) => {
      expect(url.searchParams.get('project')).toBe('Work');
      expect(url.searchParams.get('q')).toBe('Task');
      expect(url.searchParams.get('status')).toBe('open');
      const filtered = url.searchParams.get('priority_only') === 'true';
      const children = [saved, sibling].filter(
        (item) => !filtered || item.is_priority,
      );
      const group = epicGroup(10, children);
      group.total_count = 2;
      return {
        items: children.length ? [group] : [],
        total: children.length ? 1 : 0,
        matching_count: children.length,
      };
    });
    fixtureAPI.mock(
      'PATCH',
      '/api/action-items/1',
      async ({ request }: APIRequest) => {
        const body = request.postDataJSON();
        expect(body).toEqual({
          expected_revision: saved.revision,
          is_priority: !saved.is_priority,
        });
        writes.push(body);
        if (writes.length === 1) await gate.promise;
        saved = {
          ...saved,
          is_priority: body.is_priority,
          revision: saved.revision + 1,
        };
        return saved;
      },
    );
    await page.goto('/action-items?project=Work&q=Task');
    await expect(
      page.getByRole('button', { name: 'Task 1', exact: true }),
    ).toBeEnabled();
    if (scale === 2) await enlargeComputedText(page);
    const quickFilter = page.getByRole('checkbox', {
      name: 'Priority only',
      exact: true,
    });
    await expectControlReachable(quickFilter);
    await openItemActions(page, 'Task 1');
    const mark = page.getByRole('button', {
      name: 'Mark Task 1 as Priority',
      exact: true,
    });
    await expectControlReachable(mark);
    await expect(mark).toHaveAttribute('aria-pressed', 'false');
    await mark.click();
    await expect.poll(() => writes.length).toBe(1);
    await expect(quickFilter).toBeDisabled();
    gate.resolve();
    await expect(quickFilter).toBeEnabled();
    await expect(
      page
        .locator('.action-item-row')
        .first()
        .getByLabel('Order 1', { exact: true }),
    ).toHaveText('1');
    await expect(page.locator('.action-item-priority-marker')).toHaveText(
      'Priority',
    );
    await expect(
      page.getByRole('button', { name: 'More actions for Task 1' }),
    ).toBeFocused();
    await expectControlReachable(quickFilter);
    await quickFilter.check();
    await expect(
      page.getByRole('button', { name: 'Task 2', exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: 'Task 1', exact: true }),
    ).toBeVisible();
    await expect(quickFilter).toBeChecked();
    await expect(
      page.getByRole('button', { name: 'More filters', exact: true }),
    ).toBeVisible();
    await expect(page.locator('.action-items-active-filters')).toHaveCount(0);
    await expect(page.getByText('Priority only', { exact: true })).toHaveCount(
      1,
    );
    await expect
      .poll(() =>
        fixtureAPI.requests.some(
          (request) =>
            new URL(request.url).searchParams.get('priority_only') === 'true',
        ),
      )
      .toBe(true);
    await expectDocumentContained(page);
    await expectMainContained(page);
    if (['chromium-1440', 'chromium-390'].includes(testInfo.project.name)) {
      await quickFilter.scrollIntoViewIfNeeded();
      const path = testInfo.outputPath(`priority-planning-${scale}x.png`);
      await page.screenshot({ path, fullPage: true });
      await testInfo.attach('Priority planning', {
        path,
        contentType: 'image/png',
      });
    }
    await page.goto('/action-items');
    await expect(quickFilter).toBeChecked();
    await expect(
      page.getByRole('button', { name: 'Task 1', exact: true }),
    ).toBeEnabled();
    await expect(
      page.getByRole('button', { name: 'Task 2', exact: true }),
    ).toHaveCount(0);
    await openItemActions(page, 'Task 1');
    const remove = page.getByRole('button', {
      name: 'Remove Priority from Task 1',
      exact: true,
    });
    await expect(remove).toHaveAttribute('aria-pressed', 'true');
    await remove.click();
    await expect(
      page.getByRole('button', { name: 'Task 1', exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: 'Collapse Epic Release' }),
    ).toHaveCount(0);
    await expect(quickFilter).toBeChecked();
    expect(writes).toEqual([
      { expected_revision: 1, is_priority: true },
      { expected_revision: 2, is_priority: false },
    ]);
    expect(saved.priority).toBe(1);
    expect(saved.status).toBe('open');
    expect(
      fixtureAPI.requests.filter((request) => request.method !== 'GET'),
    ).toHaveLength(2);
  });
}
