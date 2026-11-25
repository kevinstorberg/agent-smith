import { expect, type Page } from '@playwright/test';
import type { ActionItemSort } from '../src/api';

export function compactActionItems(page: Page) {
  return page.viewportSize()!.width <= 1100;
}

export function actionItemSortControl(page: Page, label: string) {
  return compactActionItems(page)
    ? page.getByRole('combobox', { name: 'Sort by', exact: true })
    : page
        .locator('.action-item-grouped-table > thead')
        .getByRole('button', { name: label, exact: true });
}

export async function selectActionItemSort(
  page: Page,
  label: string,
  sort: ActionItemSort,
) {
  const control = actionItemSortControl(page, label);
  if (compactActionItems(page)) await control.selectOption(sort);
  else await control.click();
}

export async function expectActionItemSort(
  page: Page,
  label: string,
  sort: ActionItemSort,
  direction: 'ascending' | 'descending',
) {
  const control = actionItemSortControl(page, label);
  if (compactActionItems(page)) await expect(control).toHaveValue(sort);
  else
    await expect(control.locator('xpath=ancestor::th')).toHaveAttribute(
      'aria-sort',
      direction,
    );
}
