import { expect, type Locator, type Page } from '@playwright/test';

export async function openDisclosure(
  scope: Page | Locator,
  label: string | RegExp,
) {
  const trigger = scope.getByRole('button', { name: label, exact: true });
  await expect(trigger).toBeEnabled();
  if ((await trigger.getAttribute('aria-expanded')) !== 'true')
    await trigger.click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  return trigger;
}

export function openItemActions(page: Page, title: string) {
  return openDisclosure(page, `More actions for ${title}`);
}

export function openEpicActions(page: Page, title: string) {
  return openDisclosure(page, `Actions for Epic ${title}`);
}

export function openProjectOptions(page: Page) {
  return openDisclosure(page, 'Project options');
}

export function openAdvancedFilters(page: Page) {
  return openDisclosure(page, /^Filters\b/);
}
