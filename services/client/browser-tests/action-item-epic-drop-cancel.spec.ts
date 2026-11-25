import { test, expect } from './fixtures';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import { epicGroup } from '../src/pages/__tests__/actionItemEpicFixture';

test('releasing a task over a disabled filter control cancels without a write', async ({
  page,
  fixtureAPI,
}) => {
  const item = actionItem(2);
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items/queue', {
    items: [epicGroup(10, [item])],
    total: 1,
    matching_count: 1,
  });
  await page.goto('/action-items');
  const handle = page.getByRole('button', {
    name: `Reorder ${item.title}`,
    exact: true,
  });
  await expect(handle).toBeEnabled();
  await handle.scrollIntoViewIfNeeded();
  const origin = (await handle.boundingBox())!;
  await page.mouse.move(
    origin.x + origin.width / 2,
    origin.y + origin.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    origin.x + origin.width / 2,
    origin.y + origin.height / 2 + 10,
    { steps: 4 },
  );
  const list = page.getByRole('region', {
    name: 'action items list',
    exact: true,
  });
  await expect(list).toHaveAttribute('data-dragging', 'true');
  const disabled = page.getByRole('button', { name: /^More filters/ });
  await expect(disabled).toBeDisabled();
  await disabled.scrollIntoViewIfNeeded();
  const target = (await disabled.boundingBox())!;
  await page.mouse.move(
    target.x + target.width / 2,
    target.y + target.height / 2,
    { steps: 12 },
  );
  await page.mouse.up();
  await expect(list).toHaveAttribute('data-dragging', 'false');
  await expect(handle).toBeEnabled();
  expect(
    fixtureAPI.requests.filter((request) => request.method !== 'GET'),
  ).toEqual([]);
});
