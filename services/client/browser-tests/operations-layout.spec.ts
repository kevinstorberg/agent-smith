import type { Locator } from '@playwright/test';
import { test, expect } from './fixtures';
import {
  expectControlContained,
  expectControlsUnclipped,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import {
  auditFixture,
  proposalFixture,
  runFixture,
  scenarioFixture,
  suiteFixture,
} from './operationsFixture';
import { enlargeComputedText } from './typography';

async function exerciseScroll(region: Locator) {
  await expect(region).toHaveAttribute('tabindex', '0');
  await region.focus();
  if (
    await region.evaluate(
      (element) => element.scrollWidth > element.clientWidth,
    )
  ) {
    await region.press('ArrowRight');
    await expect
      .poll(() => region.evaluate((element) => element.scrollLeft))
      .toBeGreaterThan(0);
  }
}

function resultOptions(register: (path: string, response: unknown) => void) {
  register('/api/evals/categories', ['rules']);
  register('/api/evals/subcategories', ['release']);
  register('/api/evals/facets', {
    scenarios: [runFixture().scenario],
    models: [runFixture().test_model],
  });
  register('/api/evals/chart/average', []);
}

test('Audit list scrolls locally and long detail identifiers wrap inside their values', async ({
  page,
  fixtureAPI,
}) => {
  const event = auditFixture();
  fixtureAPI.get('/api/audit/events', { items: [event], total: 1 });
  fixtureAPI.get('/api/audit/counts', { claude: 1, codex: 0, gemini: 0 });
  fixtureAPI.get('/api/audit/events/1', event);
  await page.goto('/audit');
  const region = page.getByRole('region', {
    name: 'Audit events',
    exact: true,
  });
  await expect(
    region.getByRole('cell', { name: event.tool_name }),
  ).toBeVisible();
  await exerciseScroll(region);
  const project = region.getByRole('cell', {
    name: event.project!,
    exact: true,
  });
  await project.scrollIntoViewIfNeeded();
  await expectControlContained(project, region);
  await expectMainContained(page);
  await region.getByRole('cell', { name: event.tool_name }).click();
  await expect(page).toHaveURL(/\/audit\/1$/);
  await expect(page.getByText(event.session_id, { exact: true })).toBeVisible();
  if (page.viewportSize()!.width <= 390) {
    const label = (await page
      .getByText('Session', { exact: true })
      .boundingBox())!;
    const value = (await page
      .getByText(event.session_id, { exact: true })
      .boundingBox())!;
    expect(value.x).toBeCloseTo(label.x);
    expect(value.y).toBeGreaterThanOrEqual(label.y + label.height);
  }
  for (const value of [event.session_id, event.correlation_key]) {
    const text = page.getByText(value, { exact: true });
    const geometry = await text.evaluate((element) => {
      const range = document.createRange();
      range.selectNodeContents(element);
      const bounds = element
        .closest('.audit-detail-row')!
        .getBoundingClientRect();
      return {
        right: bounds.right,
        textRight: Math.max(
          ...[...range.getClientRects()].map((rect) => rect.right),
        ),
      };
    });
    expect(geometry.textRight).toBeLessThanOrEqual(geometry.right + 1);
  }
  for (const pane of await page.locator('.operations-content-pane').all())
    await expectControlContained(pane, page.locator('#main-content'));
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('Proposals retain readable titles and reachable review actions through an empty result', async ({
  page,
  fixtureAPI,
}) => {
  let pending = true;
  fixtureAPI.get('/api/proposals', () => ({
    items: pending ? [proposalFixture()] : [],
    total: pending ? 1 : 0,
  }));
  fixtureAPI.get('/api/proposals/counts', () => ({
    pending: pending ? 1 : 0,
    approved: 0,
    rejected: pending ? 0 : 1,
  }));
  fixtureAPI.mock('POST', '/api/proposals/1/reject', () => {
    pending = false;
    return { ...proposalFixture(), status: 'rejected' };
  });
  await page.goto('/proposals');
  const region = page.getByRole('region', {
    name: 'Proposals list',
    exact: true,
  });
  const title = region.getByRole('cell', {
    name: proposalFixture().title,
    exact: true,
  });
  await expect(title).toBeVisible();
  expect((await title.boundingBox())!.width).toBeGreaterThanOrEqual(200);
  await exerciseScroll(region);
  const reject = region.getByRole('button', { name: 'Reject', exact: true });
  await reject.scrollIntoViewIfNeeded();
  await expectControlContained(reject, region);
  await reject.click();
  const empty = region.getByText('No pending proposals', { exact: true });
  await expect(empty).toBeVisible();
  await expectControlContained(empty, region);
  await expect(region.getByRole('columnheader')).toHaveCount(6);
  await expect(
    region.getByRole('columnheader').getByRole('button'),
  ).toHaveCount(5);
  await exerciseScroll(region);
  await expectControlContained(empty, region);
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('Results keep scenario text readable and rightmost scores reachable', async ({
  page,
  fixtureAPI,
}) => {
  const run = runFixture();
  fixtureAPI.get('/api/evals', { items: [run], total: 1 });
  resultOptions(fixtureAPI.get);
  fixtureAPI.get('/api/evals/1', {
    ...run,
    prompt: 'Review release context',
    output: 'Ready',
    results: [],
  });
  await page.goto('/evals');
  const region = page.getByRole('region', {
    name: 'Results list',
    exact: true,
  });
  const scenario = region.getByRole('cell', {
    name: run.scenario,
    exact: true,
  });
  await expect(scenario).toBeVisible();
  expect((await scenario.boundingBox())!.width).toBeGreaterThanOrEqual(200);
  await exerciseScroll(region);
  const scores = region.getByText('8.0 (2 rules)', { exact: true });
  await scores.scrollIntoViewIfNeeded();
  await expectControlContained(scores, region);
  await expectMainContained(page);
  await scenario.click();
  await expect(page).toHaveURL(/\/evals\/1$/);
  await page.getByRole('button', { name: 'Agent Output', exact: true }).click();
  await expect(page.getByText('Ready', { exact: true })).toBeVisible();
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('Eval suite Results links remain keyboard reachable in the rightmost column', async ({
  page,
  fixtureAPI,
}) => {
  const suite = suiteFixture();
  fixtureAPI.get('/api/eval-configs/suites', { items: [suite], total: 1 });
  fixtureAPI.get('/api/evals', { items: [], total: 0 });
  resultOptions(fixtureAPI.get);
  await page.goto('/eval-configs');
  const region = page.getByRole('region', { name: 'Eval suites', exact: true });
  const title = region.getByRole('cell', { name: suite.name, exact: true });
  await expect(title).toBeVisible();
  expect((await title.boundingBox())!.width).toBeGreaterThanOrEqual(200);
  await exerciseScroll(region);
  const results = region.getByRole('link', { name: 'Results →' });
  await results.focus();
  await expectControlContained(results, region);
  await expectMainContained(page);
  await results.press('Enter');
  await expect(page).toHaveURL(/\/evals\?category=rules&subcategory=release$/);
  await expect(
    page.getByText('No eval runs found', { exact: true }),
  ).toBeVisible();
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('Suite scenario actions and edit controls remain readable without widening the page', async ({
  page,
  fixtureAPI,
}) => {
  const suite = suiteFixture();
  const scenario = scenarioFixture();
  fixtureAPI.get('/api/eval-configs/suites/1', {
    ...suite,
    scenarios: [scenario],
  });
  await page.goto('/eval-configs/1');
  const region = page.getByRole('region', {
    name: 'Suite scenarios',
    exact: true,
  });
  await expect(
    region.getByRole('cell', { name: scenario.name, exact: true }),
  ).toBeVisible();
  await exerciseScroll(region);
  const remove = region.getByRole('button', { name: 'Delete', exact: true });
  await remove.scrollIntoViewIfNeeded();
  await expectControlContained(remove, region);
  expect(
    await remove.evaluate((element) =>
      parseFloat(getComputedStyle(element).fontSize),
    ),
  ).toBeGreaterThanOrEqual(12);
  page.once('dialog', (dialog) => dialog.dismiss());
  await remove.click();
  await expect(
    region.getByRole('cell', { name: scenario.name, exact: true }),
  ).toBeVisible();
  await region
    .getByRole('button', { name: 'Edit scenario', exact: true })
    .click();
  const cancel = region.getByRole('button', { name: 'Cancel', exact: true });
  await cancel.scrollIntoViewIfNeeded();
  await expectControlContained(cancel, region);
  await cancel.click();
  await expect(
    region.getByRole('button', { name: 'Cancel', exact: true }),
  ).not.toBeVisible();
  await page
    .getByRole('button', { name: '+ Add Scenario', exact: true })
    .click();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
});

test('Jobs empty messages stay centered in the visible table', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/jobs', { items: [], total: 0 });
  await page.goto('/jobs');
  const region = page.getByRole('region', { name: 'Jobs list', exact: true });
  const empty = region.getByText('No jobs found', { exact: true });
  await expect(empty).toHaveCSS('text-align', 'center');
  await expect(empty).toHaveCSS('padding-top', '32px');
  await expect(region.getByRole('columnheader')).toHaveCount(4);
  await expectControlContained(empty, region);
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('Proposal create previews keep long content inside their panes', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/proposals/1', proposalFixture());
  await page.goto('/proposals/1');
  await expect(
    page.getByRole('heading', { name: proposalFixture().title }),
  ).toBeVisible();
  const pane = page.locator('.operations-content-pane');
  await expect(pane).toBeVisible();
  await expectControlContained(pane, page.locator('#main-content'));
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
});

for (const resource of [
  {
    route: '/proposals',
    endpoint: '/api/proposals',
    label: 'Proposals list',
    error: 'Could not load proposals.',
    empty: 'No pending proposals',
    headerCount: 6,
    sortButtonCount: 5,
  },
  {
    route: '/audit',
    endpoint: '/api/audit/events',
    label: 'Audit events',
    error: 'Could not load audit events.',
    empty: 'No tool calls yet',
    headerCount: 6,
  },
  {
    route: '/evals',
    endpoint: '/api/evals',
    label: 'Results list',
    error: 'Could not load results.',
    empty: 'No eval runs found',
    headerCount: 6,
  },
  {
    route: '/eval-configs',
    endpoint: '/api/eval-configs/suites',
    label: 'Eval suites',
    error: 'Could not load eval suites.',
    empty: 'No eval suites found',
    headerCount: 6,
    sortButtonCount: 5,
  },
]) {
  test(`${resource.label} recover from an error into a contained empty state`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    fixtureAPI.get(
      resource.endpoint,
      { detail: 'Synthetic unavailable response' },
      503,
    );
    if (resource.route === '/proposals')
      fixtureAPI.get('/api/proposals/counts', {
        pending: 0,
        approved: 0,
        rejected: 0,
      });
    if (resource.route === '/audit')
      fixtureAPI.get('/api/audit/counts', { claude: 0, codex: 0, gemini: 0 });
    if (resource.route === '/evals') resultOptions(fixtureAPI.get);
    await page.goto(resource.route);
    await expect(page.getByRole('alert')).toContainText(resource.error);
    await expect(
      page.getByRole('textbox', { name: 'Search', exact: true }),
    ).toBeVisible();
    fixtureAPI.get(resource.endpoint, { items: [], total: 0 });
    await page.getByRole('button', { name: 'Retry', exact: true }).click();
    const region = page.getByRole('region', {
      name: resource.label,
      exact: true,
    });
    const empty = region.getByText(resource.empty, { exact: true });
    await expect(empty).toBeVisible();
    await expect(region.getByRole('columnheader')).toHaveCount(
      resource.headerCount,
    );
    await expectControlContained(empty, region);
    if (resource.headerCount === 0) {
      expect(
        await region.evaluate(
          (element) => element.scrollWidth - element.clientWidth,
        ),
      ).toBeLessThanOrEqual(1);
    } else {
      await expect(
        region.getByRole('columnheader').getByRole('button'),
      ).toHaveCount(resource.sortButtonCount ?? resource.headerCount);
      const initialFont = await empty.evaluate((element) =>
        parseFloat(getComputedStyle(element).fontSize),
      );
      for (const scale of [1, 2]) {
        if (scale === 2) await enlargeComputedText(page);
        expect(
          await empty.evaluate((element) =>
            parseFloat(getComputedStyle(element).fontSize),
          ),
        ).toBeCloseTo(initialFont * scale, 1);
        await empty.scrollIntoViewIfNeeded();
        for (const end of [false, true]) {
          await region.evaluate((element, end) => {
            element.scrollLeft = end ? element.scrollWidth : 0;
          }, end);
          if (
            end &&
            (await region.evaluate(
              (element) => element.scrollWidth > element.clientWidth,
            ))
          )
            expect(
              await region.evaluate((element) => element.scrollLeft),
            ).toBeGreaterThan(0);
          await expectControlContained(empty, region);
          const glyphs = await empty.evaluate((element) => {
            const range = document.createRange();
            range.selectNodeContents(element);
            const bounds = element.getBoundingClientRect();
            return {
              left: bounds.left,
              right: bounds.right,
              top: bounds.top,
              bottom: bounds.bottom,
              viewportHeight: innerHeight,
              fragments: [...range.getClientRects()].map((rect) => ({
                left: rect.left,
                right: rect.right,
              })),
            };
          });
          expect(glyphs.fragments.length).toBeGreaterThan(0);
          expect(glyphs.top).toBeGreaterThanOrEqual(0);
          expect(glyphs.bottom).toBeLessThanOrEqual(glyphs.viewportHeight);
          for (const fragment of glyphs.fragments) {
            expect(fragment.left).toBeGreaterThanOrEqual(glyphs.left);
            expect(fragment.right).toBeLessThanOrEqual(glyphs.right);
          }
          await page.screenshot({
            path: testInfo.outputPath(
              `empty-${resource.route.slice(1)}-${scale}x-${end ? 'end' : 'start'}.png`,
            ),
          });
        }
      }
    }
    await expectDocumentContained(page);
    await expectMainContained(page);
    await expectControlsUnclipped(page);
  });
}

for (const route of ['/eval-configs/new', '/eval-configs/1']) {
  test(`Suite form fields wrap inside their card at ${route}`, async ({
    page,
    fixtureAPI,
  }) => {
    if (route.endsWith('/1'))
      fixtureAPI.get('/api/eval-configs/suites/1', suiteFixture());
    await page.goto(route);
    if (route.endsWith('/1'))
      await page.getByRole('button', { name: 'Edit', exact: true }).click();
    const fields = page.locator('.eval-suite-fields input');
    await expect(fields).toHaveCount(2);
    if (page.viewportSize()!.width <= 390) {
      const first = (await fields.nth(0).boundingBox())!;
      const second = (await fields.nth(1).boundingBox())!;
      expect(second.y).toBeGreaterThanOrEqual(first.y + first.height + 8);
    }
    for (const input of await fields.all()) {
      await expectControlContained(input, page.locator('.eval-suite-fields'));
      await input.fill('release_context_'.repeat(10));
    }
    await expectDocumentContained(page);
    await expectMainContained(page);
    await expectControlsUnclipped(page);
  });
}
