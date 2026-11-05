import type { Page } from '@playwright/test';

export async function enlargeComputedText(
  page: Page,
  scale = 2,
  options: { preserveMotion?: boolean } = {},
) {
  if (!Number.isFinite(scale) || scale <= 0)
    throw new Error('Text scale must be positive and finite');
  if (!options.preserveMotion)
    await page.addStyleTag({
      content:
        '*, *::before, *::after { transition: none !important; animation: none !important; }',
    });
  await page.evaluate(async (scale) => {
    await document.fonts.ready;
    const snapshot = [
      ...document.querySelectorAll<HTMLElement>('body, body *'),
    ].map((element) => {
      const style = getComputedStyle(element);
      return {
        element,
        font: parseFloat(style.fontSize),
        line: parseFloat(style.lineHeight),
      };
    });
    // Snapshot before applying styles so inherited sizes are enlarged only once.
    for (const { element, font, line } of snapshot) {
      element.style.fontSize = `${font * scale}px`;
      if (Number.isFinite(line)) element.style.lineHeight = `${line * scale}px`;
    }
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
  }, scale);
}
