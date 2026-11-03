import { expect, type Locator } from '@playwright/test';

export async function expectContrast(target: Locator, minimum = 4.5, property: 'color' | 'borderTopColor' = 'color') {
  const ratios = await target.evaluate((element, property) => {
    type Color = [number, number, number, number];
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 1;
    const context = canvas.getContext('2d')!;
    const color = (value: string): Color => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
      return [r, g, b, a / 255];
    };
    const over = (front: Color, back: Color): Color => [
      front[0] * front[3] + back[0] * (1 - front[3]),
      front[1] * front[3] + back[1] * (1 - front[3]),
      front[2] * front[3] + back[2] * (1 - front[3]), 1,
    ];
    const luminance = (value: Color) => value.slice(0, 3).map(channel => {
      const srgb = channel / 255;
      return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
    }).reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
    const ancestors: Element[] = [];
    for (let parent: Element | null = element; parent; parent = parent.parentElement) ancestors.unshift(parent);
    let backgrounds: Color[] = [[255, 255, 255, 1]];
    for (const ancestor of ancestors) {
      const style = getComputedStyle(ancestor);
      if (Number(style.opacity) !== 1) throw new Error('Contrast fixture must use an enabled, opaque group');
      backgrounds = backgrounds.map(background => over(color(style.backgroundColor), background));
      if (style.backgroundImage !== 'none') {
        if (!style.backgroundImage.startsWith('linear-gradient(')) throw new Error('Contrast fixture contains an unsupported background image');
        const stops = style.backgroundImage.match(/rgba?\([^)]+\)/g);
        if (!stops?.length) throw new Error('Gradient colors could not be resolved');
        backgrounds = backgrounds.flatMap(background => stops.map(stop => over(color(stop), background)));
      }
    }
    const foreground = color(getComputedStyle(element)[property]);
    return backgrounds.map(background => {
      const front = luminance(over(foreground, background));
      const back = luminance(background);
      return (Math.max(front, back) + 0.05) / (Math.min(front, back) + 0.05);
    });
  }, property);
  expect(Math.min(...ratios), `${property} contrast includes rendered alpha backgrounds and gradient stops`).toBeGreaterThanOrEqual(minimum);
}
