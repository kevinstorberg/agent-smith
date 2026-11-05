import { test, expect } from './fixtures';
import { expectDocumentContained, expectMainContained } from './geometry';

test('Navigation stays compact on mobile and supports keyboard recovery', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/memory/list', { items: [], total: 0 });
  fixtureAPI.get('/api/action-items', { items: [], total: 0 });
  await page.goto('/memory');
  await expect(
    page.getByRole('heading', { name: 'Memory', exact: true }),
  ).toBeVisible();
  if (page.viewportSize()!.width > 768) {
    await expect(
      page.getByRole('button', { name: 'Menu', exact: true }),
    ).toBeHidden();
    await expect(
      page.getByRole('link', { name: 'Action items', exact: true }),
    ).toBeVisible();
  } else {
    const sidebar = page.getByRole('navigation', {
      name: 'Primary navigation',
      exact: true,
    });
    const menu = page.getByRole('button', { name: 'Menu', exact: true });
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    expect((await sidebar.boundingBox())!.height).toBeLessThanOrEqual(80);
    await menu.click();
    await expect(
      page.getByRole('button', { name: 'Close menu', exact: true }),
    ).toHaveAttribute('aria-expanded', 'true');
    const link = page.getByRole('link', { name: 'Action items', exact: true });
    await link.focus();
    await page.keyboard.press('Escape');
    await expect(menu).toBeFocused();
    await expect(link).toBeHidden();
    await menu.click();
    await link.click();
    await expect(
      page.getByRole('heading', { name: 'Action items', exact: true }),
    ).toBeVisible();
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await expect(page.locator('#main-content')).toBeFocused();
  }
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test.beforeEach(async ({ fixtureAPI }) => {
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
});
