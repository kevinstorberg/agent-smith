import { test, expect } from './fixtures';
import { expectControlContained } from './geometry';

async function scrollingControl(page: import('@playwright/test').Page, overflow: 'auto' | 'hidden') {
  await page.setContent(`<div role="region" aria-label="Scrollable controls" style="width:180px;height:80px;overflow-x:${overflow}">
    <div style="width:600px"><button style="margin-left:480px;width:80px">Results</button></div>
  </div>`);
  return { region: page.getByRole('region', { name: 'Scrollable controls' }), control: page.getByRole('button', { name: 'Results' }) };
}

test('Containment waits for horizontal scrolling to settle', async ({ page }) => {
  const { region, control } = await scrollingControl(page, 'auto');
  await region.evaluate(element => {
    const maximum = element.scrollWidth - element.clientWidth;
    const start = performance.now();
    const advance = (now: number) => {
      const progress = Math.min(1, (now - start) / 750);
      element.scrollLeft = maximum * progress;
      if (progress < 1) requestAnimationFrame(advance);
    };
    requestAnimationFrame(advance);
  });
  await expectControlContained(control, region);
});

test('Containment still rejects a permanently clipped control', async ({ page }) => {
  const { region, control } = await scrollingControl(page, 'hidden');
  await expect(expectControlContained(control, region)).rejects.toThrow('Control must remain inside its container');
});
