import type { Page } from '@playwright/test';

export async function enlargeComputedText(
  page: Page,
  scale = 2,
  options: { preserveMotion?: boolean; restorable?: boolean } = {},
) {
  if (!Number.isFinite(scale) || scale <= 0)
    throw new Error('Text scale must be positive and finite');
  if (!options.preserveMotion)
    await page.addStyleTag({
      content:
        '*, *::before, *::after { transition: none !important; animation: none !important; }',
    });
  const originalStyles = await page.evaluateHandle(async (scale) => {
    await document.fonts.ready;
    const snapshot = [
      ...document.querySelectorAll<HTMLElement>('body, body *'),
    ].map((element) => {
      const style = getComputedStyle(element);
      return {
        element,
        font: parseFloat(style.fontSize),
        line: parseFloat(style.lineHeight),
        fontSize: element.style.fontSize,
        lineHeight: element.style.lineHeight,
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
    // Font transitions move scroll anchors and can cancel a pending mouse drag.
    await Promise.allSettled(
      document
        .getAnimations()
        .filter(
          (animation) =>
            animation instanceof CSSTransition &&
            ['font-size', 'line-height'].includes(animation.transitionProperty),
        )
        .map((animation) => animation.finished),
    );
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
    return snapshot;
  }, scale);
  if (!options.restorable) {
    await originalStyles.dispose();
    return null;
  }
  return async function restoreComputedText() {
    await originalStyles.evaluate((snapshot) => {
      for (const { element, fontSize, lineHeight } of snapshot) {
        element.style.fontSize = fontSize;
        element.style.lineHeight = lineHeight;
      }
    });
    await originalStyles.dispose();
  };
}
