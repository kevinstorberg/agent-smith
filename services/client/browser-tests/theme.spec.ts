import { harnessFixture } from './harnessFixture';
import { test, expect } from './fixtures';
import { expectContrast } from './contrast';
import { expectDocumentContained, expectMainContained } from './geometry';

const item = harnessFixture({ clone_as_skill: true });

test('Table toggle labels remain readable in normal and hovered rows', async ({ page, fixtureAPI }) => {
  fixtureAPI.get('/api/harness/items/rule', { items: [item], total: 1 });
  await page.goto('/harness/rules');
  const row = page.locator('.harness-list-row');
  await expect(row).toHaveCount(1);
  const labels = row.locator('label span');
  await expect(labels).toHaveCount(2);
  await expect(row.getByRole('checkbox', { name: `Enable ${item.name}`, exact: true })).toBeChecked();
  await expect(row.getByRole('checkbox', { name: `Clone ${item.name} as a skill`, exact: true })).toBeChecked();
  for (const label of await labels.all()) await expectContrast(label);
  await row.hover();
  for (const label of await labels.all()) await expectContrast(label);
});

test('Text roles remain readable on tinted cards and navigation', async ({ page, fixtureAPI }) => {
  fixtureAPI.get('/api/harness/items/rule/1', item);
  fixtureAPI.get('/api/harness/items/rule/1/history', []);
  await page.goto('/harness/rule/1');
  await expect(page.getByRole('heading', { name: item.name, exact: true })).toBeVisible();
  for (const target of [page.locator('.sidebar-link.active'), page.locator('.tag-danger'), page.locator('.tag-info'),
    page.getByRole('button', { name: 'Delete', exact: true }), page.locator('.markdown-content p')]) await expectContrast(target);
  await expect(page.locator('.page-title')).toHaveCSS('font-size', '24px');
  await expectContrast(page.getByRole('button', { name: 'Edit', exact: true }));
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('Field boundaries remain visible without increasing decorative card borders', async ({ page, fixtureAPI }) => {
  fixtureAPI.get('/api/plans', { items: [], total: 0 });
  await page.goto('/plans');
  await expect(page.getByText('No plans found')).toBeVisible();
  const field = page.getByRole('textbox', { name: 'Search plans' });
  await expectContrast(field, 3, 'borderTopColor');
  await expectContrast(field);
  await expectContrast(page.locator('.form-label').first());
  await expectDocumentContained(page);
  await expectMainContained(page);
});
