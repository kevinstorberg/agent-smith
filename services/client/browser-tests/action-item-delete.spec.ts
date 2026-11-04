import { test, expect, type APIRequest } from './fixtures';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import {
  expectControlContained,
  expectControlReachable,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { enlargeComputedText } from './typography';

test('Action Items confirms cancellation and keyboard deletion with the displayed revision', async ({
  page,
  fixtureAPI,
}) => {
  let rows = [actionItem(1, { revision: 7 }), actionItem(2)];
  let deletes = 0;
  fixtureAPI.get('/api/action-items', () => ({
    items: rows,
    total: rows.length,
  }));
  fixtureAPI.mock(
    'DELETE',
    '/api/action-items/1',
    ({ request }: APIRequest) => {
      expect(request.postDataJSON()).toEqual({ expected_revision: 7 });
      deletes += 1;
      rows = rows.filter((row) => row.id !== 1);
      return { deleted: true, id: 1 };
    },
  );
  await page.goto('/action-items');
  const remove = page.getByRole('button', {
    name: 'Delete Task 1',
    exact: true,
  });
  await expectControlReachable(remove);
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toBe('Delete action item “Task 1”?');
    await dialog.dismiss();
  });
  await remove.click();
  expect(deletes).toBe(0);
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toHaveAttribute('aria-expanded', 'false');
  await remove.focus();
  page.once('dialog', (dialog) => dialog.accept());
  await page.keyboard.press('Enter');
  await expect(
    page.getByRole('button', { name: 'Task 1', exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Delete Task 2', exact: true }),
  ).toBeEnabled();
  expect(deletes).toBe(1);
  expect(
    fixtureAPI.requests.filter((request) => request.method === 'DELETE'),
  ).toHaveLength(1);
  await expect(page).toHaveURL(/\/action-items(?:\?|$)/);
  await expectDocumentContained(page);
  await expectMainContained(page);
});

for (const scale of [1, 2]) {
  test(`Action Items keeps all row controls contained at ${scale}x text`, async ({
    page,
    fixtureAPI,
  }) => {
    const row = actionItem(1, {
      title:
        'A longer action item title with project context and useful identifying detail',
    });
    fixtureAPI.get('/api/action-items', { items: [row], total: 1 });
    await page.goto('/action-items');
    const remove = page.getByRole('button', {
      name: `Delete ${row.title}`,
      exact: true,
    });
    await expect(remove).toBeEnabled();
    if (scale === 2) await enlargeComputedText(page);
    const actions = remove.locator('..');
    const cell = actions.locator('..');
    for (const button of await actions.getByRole('button').all()) {
      await expectControlContained(button, cell);
      await expectControlReachable(button);
      const [control, bounds] = await Promise.all([
        button.boundingBox(),
        cell.boundingBox(),
      ]);
      expect(control!.y).toBeGreaterThanOrEqual(bounds!.y - 1);
      expect(control!.y + control!.height).toBeLessThanOrEqual(
        bounds!.y + bounds!.height + 1,
      );
    }
    await expectDocumentContained(page);
    await expectMainContained(page);
  });
}
