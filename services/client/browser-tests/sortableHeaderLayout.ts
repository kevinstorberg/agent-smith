import type { Locator, Page, TestInfo } from '@playwright/test';
import { expect } from '@playwright/test';
import { expectControlReachable, expectDocumentContained } from './geometry';
import { enlargeComputedText } from './typography';

interface HeaderLayoutOptions {
  table: Locator;
  scrollRegion: Locator;
  labels: readonly string[];
  artifactPrefix: string;
  fullyVisibleHeaders?: readonly string[];
  maximumLines?: Readonly<Record<string, number>>;
  assertLayout?: (scale: 1 | 2) => Promise<void>;
}

export async function expectSortableHeaderLayout(
  page: Page,
  testInfo: TestInfo,
  options: HeaderLayoutOptions,
) {
  if (
    !options.labels.length ||
    !/^[a-z0-9][a-z0-9-]*$/.test(options.artifactPrefix)
  )
    throw new Error(
      'Header layout requires labels and a portable artifact prefix',
    );
  const initialFonts = new Map<string, number>();
  for (const scale of [1, 2] as const) {
    if (scale === 2) await enlargeComputedText(page);
    const measurements = [];
    for (const name of options.labels) {
      const header = options.table.getByRole('columnheader', {
        name,
        exact: true,
      });
      const button = header.getByRole('button');
      await button.scrollIntoViewIfNeeded();
      const measurement = await button.evaluate((node) => {
        const label = node.querySelector<HTMLElement>('.sortable-header-label');
        const icon = node.querySelector<HTMLElement>('.sortable-header-icon');
        if (!label || !icon || !label.textContent?.trim())
          throw new Error(
            'Shared sortable header requires a visible label and decorative icon',
          );
        const texts: { node: Text; start: number; end: number }[] = [];
        const walker = document.createTreeWalker(label, NodeFilter.SHOW_TEXT);
        let offset = 0;
        for (let text = walker.nextNode(); text; text = walker.nextNode()) {
          const length = text.textContent!.length;
          texts.push({
            node: text as Text,
            start: offset,
            end: offset + length,
          });
          offset += length;
        }
        const range = document.createRange();
        const words = [...label.textContent.matchAll(/\S+/g)].map((word) => {
          const start = word.index!;
          const end = start + word[0].length;
          const first = texts.find(
            (text) => text.start <= start && text.end > start,
          )!;
          const last = texts.find(
            (text) => text.start < end && text.end >= end,
          )!;
          range.setStart(first.node, start - first.start);
          range.setEnd(last.node, end - last.start);
          return {
            word: word[0],
            fragments: Array.from(range.getClientRects(), (rect) => ({
              left: rect.left,
              right: rect.right,
              top: rect.top,
              bottom: rect.bottom,
            })),
          };
        });
        const labelBox = label.getBoundingClientRect();
        const iconBox = icon.getBoundingClientRect();
        return {
          words,
          font: parseFloat(getComputedStyle(label).fontSize),
          labelRight: labelBox.right,
          icon: {
            left: iconBox.left,
            right: iconBox.right,
            top: iconBox.top,
            bottom: iconBox.bottom,
          },
        };
      });
      if (scale === 1) initialFonts.set(name, measurement.font);
      expect(measurement.font, `${name} text must actually scale`).toBeCloseTo(
        initialFonts.get(name)! * scale,
        1,
      );
      const lines = new Set<number>();
      for (const word of measurement.words) {
        const wordLines = new Set(
          word.fragments.map((fragment) => Math.round(fragment.top * 2) / 2),
        );
        expect(
          wordLines.size,
          `${name}: ${word.word} must not split at ${scale}x`,
        ).toBe(1);
        for (const fragment of word.fragments) {
          lines.add(Math.round(fragment.top * 2) / 2);
          expect(
            fragment.right,
            `${name} text must not overlap the icon`,
          ).toBeLessThanOrEqual(measurement.icon.left + 0.5);
        }
      }
      expect(
        lines.size,
        `${name} must wrap only at natural word boundaries`,
      ).toBeLessThanOrEqual(
        options.maximumLines?.[name] ?? measurement.words.length,
      );
      const gap = measurement.icon.left - measurement.labelRight;
      expect(
        gap,
        `${name} label and icon must not overlap`,
      ).toBeGreaterThanOrEqual(-0.5);
      expect(
        gap,
        `${name} icon must stay beside its label`,
      ).toBeLessThanOrEqual(16);
      await expectControlReachable(button);
      if (options.fullyVisibleHeaders?.includes(name)) {
        const [control, viewport] = await Promise.all([
          button.boundingBox(),
          options.scrollRegion.boundingBox(),
        ]);
        expect(
          control!.x,
          `${name} must fit the scroll viewport`,
        ).toBeGreaterThanOrEqual(viewport!.x);
        expect(
          control!.x + control!.width,
          `${name} must fit the scroll viewport`,
        ).toBeLessThanOrEqual(viewport!.x + viewport!.width);
      }
      measurements.push({ name, ...measurement });
    }
    await options.assertLayout?.(scale);
    await expectDocumentContained(page);
    await testInfo.attach(`${options.artifactPrefix}-${scale}x-geometry.json`, {
      body: JSON.stringify(measurements),
      contentType: 'application/json',
    });
    for (const end of [false, true]) {
      await options.scrollRegion.evaluate((node, end) => {
        node.scrollLeft = end ? node.scrollWidth : 0;
      }, end);
      const name = `${options.artifactPrefix}${end ? '-end' : ''}-${scale}x.png`;
      const path = testInfo.outputPath(name);
      await page.screenshot({ path });
      await testInfo.attach(name, { path, contentType: 'image/png' });
    }
  }
}
