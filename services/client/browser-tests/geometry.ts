import { expect, type Locator, type Page } from '@playwright/test';

export async function pageGeometry(page: Page) {
  return page.evaluate(() => {
    const main = document.querySelector<HTMLElement>('#main-content');
    return {
      viewport: { width: innerWidth, height: innerHeight },
      documentWidth: document.documentElement.scrollWidth,
      main: main ? { width: main.clientWidth, scrollWidth: main.scrollWidth } : null,
    };
  });
}

export async function expectDocumentContained(page: Page) {
  const geometry = await pageGeometry(page);
  expect(geometry.documentWidth, 'Document must not scroll horizontally').toBeLessThanOrEqual(geometry.viewport.width + 1);
}

export async function expectMainContained(page: Page) {
  const geometry = await pageGeometry(page);
  expect(geometry.main, 'The page must render its main content').not.toBeNull();
  expect(geometry.main!.scrollWidth, 'Horizontal scrolling belongs inside a named table or code region')
    .toBeLessThanOrEqual(geometry.main!.width + 1);
}

export async function expectControlContained(control: Locator, container: Locator) {
  await expect(control).toBeVisible();
  await expect(async () => {
    const [bounds, parent] = await Promise.all([control.boundingBox(), container.boundingBox()]);
    expect(bounds, 'Control must have rendered bounds').not.toBeNull();
    expect(parent, 'Control container must have rendered bounds').not.toBeNull();
    expect(bounds!.x, 'Control must remain inside its container’s left edge').toBeGreaterThanOrEqual(parent!.x - 1);
    expect(bounds!.x + bounds!.width, 'Control must remain inside its container’s right edge')
      .toBeLessThanOrEqual(parent!.x + parent!.width + 1);
  }).toPass({ timeout: 5_000, intervals: [25, 50, 100] });
}

export async function expectControlLabel(control: Locator, name: string) {
  await expect(control).toHaveAccessibleName(name);
}

export async function expectDialogContained(dialog: Locator) {
  await expect(dialog).toBeVisible();
  const bounds = await dialog.boundingBox();
  const viewport = await dialog.page().evaluate(() => ({ width: innerWidth, height: innerHeight }));
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height + 1);
  const overflow = await dialog.evaluate(element => ({ width: element.clientWidth, scrollWidth: element.scrollWidth }));
  expect(overflow.scrollWidth, 'Dialogs must contain long content without horizontal overflow').toBeLessThanOrEqual(overflow.width + 1);
}

export async function expectControlsUnclipped(page: Page) {
  const clipped = await page.locator('#main-content button, #main-content input, #main-content select, #main-content textarea').evaluateAll(controls =>
    controls.flatMap(control => {
      if (!control.getClientRects().length) return [];
      const bounds = control.getBoundingClientRect();
      for (let parent = control.parentElement; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (['auto', 'scroll'].includes(style.overflowX)) break;
        if (!['hidden', 'clip'].includes(style.overflowX)) continue;
        const container = parent.getBoundingClientRect();
        if (bounds.left < container.left - 1 || bounds.right > container.right + 1) {
          return [{ control: control.getAttribute('aria-label') || control.textContent || control.tagName, container: parent.className }];
        }
      }
      return [];
    }),
  );
  expect(clipped, 'Visible controls must not be clipped by hidden overflow').toEqual([]);
}
