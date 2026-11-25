import type { Locator } from '@playwright/test';
import { expect } from './fixtures';

export async function openEpicPicker(trigger: Locator) {
  await expect(trigger).toBeEnabled();
  if ((await trigger.getAttribute('aria-expanded')) !== 'true')
    await trigger.click();
  const id = await trigger.getAttribute('aria-controls');
  if (!id) throw new Error('Epic picker trigger must identify its disclosure');
  const panel = trigger.page().locator(`[id="${id}"]`);
  await expect(panel).toBeVisible();
  return panel;
}

export async function chooseEpic(trigger: Locator, value: string) {
  const panel = await openEpicPicker(trigger);
  await panel.locator(`button.epic-choice[value="${value}"]`).click();
  await expect(panel).toBeHidden();
}

export async function expectEpicSelection(trigger: Locator, label: string) {
  await expect(trigger.locator(':scope > span').first()).toHaveText(label);
}
