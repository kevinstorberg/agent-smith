import { test, expect, type APIRequest } from './fixtures';
import {
  expectControlsUnclipped,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { auditFixture } from './operationsFixture';
import { expectContrast } from './contrast';
import { enlargeComputedText } from './typography';

test('Audit keeps four quiet labeled fields visible and keyboard operable without records', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  fixtureAPI.get('/api/audit/events', { items: [], total: 0 });
  fixtureAPI.get('/api/audit/counts', { claude: 0, codex: 0, gemini: 0 });
  await page.goto('/audit');
  const toolbar = page.locator('.audit-toolbar');
  await expect(
    page.getByRole('heading', { name: 'No tool calls yet', exact: true }),
  ).toBeVisible();
  for (const name of ['Search', 'Project'])
    await expect(
      toolbar.getByRole('textbox', { name, exact: true }),
    ).toBeVisible();
  for (const name of ['Agent', 'Status'])
    await expect(
      toolbar.getByRole('combobox', { name, exact: true }),
    ).toBeVisible();
  const agent = toolbar.getByRole('combobox', { name: 'Agent', exact: true });
  await agent.focus();
  await agent.press('g');
  await expect(agent).toHaveValue('gemini');
  const status = toolbar.getByRole('combobox', { name: 'Status', exact: true });
  await status.focus();
  await status.press('e');
  await expect(status).toHaveValue('error');
  await page
    .getByRole('columnheader', { name: 'Duration', exact: true })
    .getByRole('button')
    .click();
  await expect
    .poll(() =>
      fixtureAPI.requests.some((entry) => {
        const url = new URL(entry.url);
        return (
          url.pathname === '/api/audit/events' &&
          url.searchParams.get('agent') === 'gemini' &&
          url.searchParams.get('status') === 'error' &&
          url.searchParams.get('sort') === 'duration'
        );
      }),
    )
    .toBe(true);
  const metrics = await toolbar.getByRole('combobox').evaluateAll((elements) =>
    elements.map((element) => {
      const select = element as HTMLSelectElement;
      const style = getComputedStyle(select);
      const context = document.createElement('canvas').getContext('2d')!;
      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      return {
        label: select.labels?.[0]?.textContent?.trim(),
        textWidth: context.measureText(select.selectedOptions[0].text).width,
        available:
          select.clientWidth -
          parseFloat(style.paddingLeft) -
          parseFloat(style.paddingRight),
        font: parseFloat(style.fontSize),
      };
    }),
  );
  for (const metric of metrics) {
    expect(metric.font).toBeGreaterThanOrEqual(14);
    expect(
      metric.textWidth,
      `${metric.label} must show its full selected value`,
    ).toBeLessThanOrEqual(metric.available + 1);
  }
  const budget = { 1440: 72, 1024: 150, 390: 300, 320: 350 }[
    page.viewportSize()!.width
  ]!;
  expect((await toolbar.boundingBox())!.height).toBeLessThanOrEqual(budget);
  await agent.selectOption('');
  await expect(agent).toHaveValue('');
  await expect(status).toHaveValue('error');
  await expect(
    page.getByRole('columnheader', { name: 'Duration', exact: true }),
  ).toHaveAttribute('aria-sort', 'descending');
  await expect
    .poll(() =>
      fixtureAPI.requests.some((entry) => {
        const url = new URL(entry.url);
        return (
          url.pathname === '/api/audit/events' &&
          !url.searchParams.has('agent') &&
          url.searchParams.get('status') === 'error' &&
          url.searchParams.get('sort') === 'duration'
        );
      }),
    )
    .toBe(true);
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
  await testInfo.attach('audit-empty.png', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });
});

test('Audit retains populated records beneath the same toolbar', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  fixtureAPI.get('/api/audit/events', { items: [auditFixture()], total: 1 });
  fixtureAPI.get('/api/audit/counts', { claude: 1, codex: 0, gemini: 0 });
  fixtureAPI.get('/api/audit/events/1', auditFixture());
  await page.goto('/audit');
  await expect(
    page.getByRole('cell', { name: auditFixture().tool_name }),
  ).toBeVisible();
  await expect(
    page
      .getByRole('combobox', { name: 'Agent', exact: true })
      .getByRole('option', { name: 'claude (1)' }),
  ).toBeAttached();
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
  await testInfo.attach('audit-populated.png', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });
  const link = page.getByRole('link', {
    name: auditFixture().tool_name,
    exact: true,
  });
  await expect(link).toHaveAttribute('href', '/audit/1');
  await expectContrast(link);
  await link.hover();
  await page.waitForTimeout(200);
  await expectContrast(link);
  await link.focus();
  await link.press('Enter');
  await expect(page).toHaveURL(/\/audit\/1$/);
  await expect(
    page.getByText(auditFixture().session_id, { exact: true }),
  ).toBeVisible();
});

test('Audit distinguishes pending, filtered empty, and failed requests without stale totals', async ({
  page,
  fixtureAPI,
}) => {
  let release: ((response: unknown) => void) | undefined;
  fixtureAPI.get('/api/audit/counts', { claude: 1, codex: 0, gemini: 0 });
  fixtureAPI.get('/api/audit/events', ({ url }: APIRequest) => {
    if (url.searchParams.get('q') === 'held')
      return new Promise((resolve) => {
        release = resolve;
      });
    return { items: [auditFixture()], total: 1 };
  });
  await page.goto('/audit');
  await expect(page.getByRole('status')).toHaveText('1 tool call');
  const search = page.getByRole('textbox', { name: 'Search', exact: true });
  await search.fill('held');
  await expect(page.getByRole('status')).toHaveCount(0);
  await expect(page.getByRole('table')).toHaveAttribute('aria-busy', 'true');
  await expect(
    page.getByText('No matching tool calls', { exact: true }),
  ).not.toBeVisible();
  await expect(
    page.getByRole('navigation', { name: 'Pagination', exact: true }),
  ).not.toBeVisible();
  await expect.poll(() => Boolean(release)).toBe(true);
  release!({ items: [], total: 0 });
  await expect(
    page.getByRole('heading', { name: 'No matching tool calls', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('status')).toHaveText('0 matching tool calls');
  fixtureAPI.get(
    '/api/audit/events',
    { detail: 'Synthetic unavailable response' },
    503,
  );
  await search.fill('failed');
  await expect(page.getByRole('alert')).toContainText(
    'Could not load audit events.',
  );
  await expect(
    page.getByText('No matching tool calls', { exact: true }),
  ).not.toBeVisible();
  for (const name of ['Agent', 'Status'])
    await expect(
      page.getByRole('combobox', { name, exact: true }),
    ).toBeVisible();
  await search.fill('failed again');
  await expect(
    page.getByRole('button', { name: 'Retry', exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole('button', { name: 'Retry', exact: true }),
  ).toBeEnabled();
  let retryRelease: ((response: unknown) => void) | undefined;
  fixtureAPI.get(
    '/api/audit/events',
    () =>
      new Promise((resolve) => {
        retryRelease = resolve;
      }),
  );
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Retry', exact: true }),
  ).toBeDisabled();
  await expect(page.locator('.audit-results')).toHaveAttribute(
    'aria-busy',
    'true',
  );
  await expect(page.getByRole('status')).toHaveCount(0);
  await expect(page.getByRole('table')).toHaveAttribute('aria-busy', 'true');
  await expect.poll(() => Boolean(retryRelease)).toBe(true);
  retryRelease!({ items: [], total: 0 });
  await expect(
    page.getByRole('heading', { name: 'No matching tool calls', exact: true }),
  ).toBeVisible();
  expect(
    new URL(
      fixtureAPI.requests
        .filter((entry) => new URL(entry.url).pathname === '/api/audit/events')
        .at(-1)!.url,
    ).searchParams.get('q'),
  ).toBe('failed again');
});

test('Audit omits unavailable global counts while keeping the accepted result total', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/audit/events', { items: [auditFixture()], total: 1 });
  fixtureAPI.get(
    '/api/audit/counts',
    { detail: 'Synthetic unavailable response' },
    503,
  );
  await page.goto('/audit');
  await expect(page.getByRole('status')).toHaveText('1 tool call');
  const options = page
    .getByRole('combobox', { name: 'Agent', exact: true })
    .locator('option');
  await expect(options).toHaveText(['All agents', 'claude', 'codex', 'gemini']);
});

test('Audit retains readable selected values after200% computed text enlargement', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/audit/events', { items: [auditFixture()], total: 1 });
  fixtureAPI.get('/api/audit/counts', { claude: 1234, codex: 0, gemini: 0 });
  await page.goto('/audit');
  await page
    .getByRole('combobox', { name: 'Agent', exact: true })
    .selectOption('claude');
  await page
    .getByRole('columnheader', { name: 'Duration', exact: true })
    .getByRole('button')
    .click();
  await expect(page.getByRole('status')).toHaveText('1 matching tool call');
  await enlargeComputedText(page);
  const toolbar = page.locator('.audit-toolbar');
  const values = await toolbar.getByRole('combobox').evaluateAll((elements) =>
    elements.map((element) => {
      const select = element as HTMLSelectElement,
        style = getComputedStyle(select);
      const context = document.createElement('canvas').getContext('2d')!;
      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      return {
        width: context.measureText(select.selectedOptions[0].text).width,
        available:
          select.clientWidth -
          parseFloat(style.paddingLeft) -
          parseFloat(style.paddingRight),
      };
    }),
  );
  for (const value of values)
    expect(value.width).toBeLessThanOrEqual(value.available + 1);
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
});
