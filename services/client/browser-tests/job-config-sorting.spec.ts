import { test, expect } from './fixtures';
import { jobFixture } from '../src/pages/__tests__/jobFixture';
import { jobConfigSortingRows } from '../src/pages/__tests__/jobConfigSortingFixture';
import { enlargeComputedText } from './typography';
import {
  expectControlContained,
  expectDocumentContained,
  expectMainContained,
} from './geometry';

for (const scale of [1, 2]) {
  test(`complete Job Configs sort locally with whole headers at ${scale}x text`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    fixtureAPI.get('/api/jobs/42', {
      ...jobFixture,
      configs: jobConfigSortingRows,
    });
    fixtureAPI.get('/api/jobs/42/executions', { items: [], total: 0 });
    await page.goto('/jobs/42');
    const table = page.getByRole('table', {
      name: 'Job configurations',
      exact: true,
    });
    const region = page.getByRole('region', {
      name: 'Job configuration list',
      exact: true,
    });
    await expect(table.getByRole('row')).toHaveCount(4);
    if (scale === 2) await enlargeComputedText(page);
    const devices = () =>
      table
        .locator('tbody tr')
        .evaluateAll((rows) =>
          rows.map((row) => row.querySelector('td')!.textContent),
        );
    await expect.poll(devices).toEqual(['Zulu', 'alpha', 'ALPHA']);
    const readsBefore = fixtureAPI.requests.filter(
      (request) => new URL(request.url).pathname === '/api/jobs/42',
    ).length;

    const device = table.getByRole('button', { name: 'Device', exact: true });
    await device.scrollIntoViewIfNeeded();
    await device.focus();
    await device.press('Enter');
    await expect.poll(devices).toEqual(['ALPHA', 'alpha', 'Zulu']);
    await device.press('Space');
    await expect.poll(devices).toEqual(['Zulu', 'ALPHA', 'alpha']);
    await expect(device).toBeFocused();

    for (const [label, ascending, descending] of [
      ['Device', ['ALPHA', 'alpha', 'Zulu'], ['Zulu', 'ALPHA', 'alpha']],
      ['Repo', ['alpha', 'Zulu', 'ALPHA'], ['ALPHA', 'Zulu', 'alpha']],
      ['Enabled', ['alpha', 'ALPHA', 'Zulu'], ['ALPHA', 'Zulu', 'alpha']],
      ['Exclude', ['ALPHA', 'Zulu', 'alpha'], ['alpha', 'ALPHA', 'Zulu']],
    ] as const) {
      const header = table.getByRole('columnheader', {
        name: label,
        exact: true,
      });
      const button = header.getByRole('button', { name: label, exact: true });
      await button.scrollIntoViewIfNeeded();
      await expectControlContained(button, header);
      await expectControlContained(button, region);
      const geometry = await button.evaluate((element) => {
        const label = element.querySelector('.sortable-header-label')!;
        const icon = element.querySelector('.sortable-header-icon')!;
        const range = document.createRange();
        range.selectNodeContents(label);
        const words = [...range.getClientRects()].map((rect) => ({
          left: rect.left,
          right: rect.right,
        }));
        const bounds = element.getBoundingClientRect();
        const iconBounds = icon.getBoundingClientRect();
        return {
          words,
          buttonLeft: bounds.left,
          buttonRight: bounds.right,
          iconLeft: iconBounds.left,
          iconRight: iconBounds.right,
        };
      });
      expect(geometry.words).toHaveLength(1);
      expect(geometry.words[0].left).toBeGreaterThanOrEqual(
        geometry.buttonLeft - 1,
      );
      expect(geometry.words[0].right).toBeLessThanOrEqual(
        geometry.iconLeft - 1,
      );
      expect(geometry.iconRight).toBeLessThanOrEqual(geometry.buttonRight + 1);
      await button.click();
      await expect.poll(devices).toEqual(ascending);
      await expect(header).toHaveAttribute('aria-sort', 'ascending');
      await button.click();
      await expect.poll(devices).toEqual(descending);
      await expect(header).toHaveAttribute('aria-sort', 'descending');
    }
    expect(
      fixtureAPI.requests.filter((request) => request.method !== 'GET'),
    ).toHaveLength(0);
    expect(
      fixtureAPI.requests.filter(
        (request) => new URL(request.url).pathname === '/api/jobs/42',
      ),
    ).toHaveLength(readsBefore);
    await expectDocumentContained(page);
    await expectMainContained(page);
    if (scale === 2) {
      const path = testInfo.outputPath('job-configs-2x.png');
      await page.screenshot({ path });
      await testInfo.attach('job-configs-2x', {
        path,
        contentType: 'image/png',
      });
    }
  });
}
