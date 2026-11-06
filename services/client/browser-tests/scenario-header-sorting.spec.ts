import { test, expect, type APIRequest } from './fixtures';
import { suiteFixture } from './operationsFixture';
import { scenarioSortingRows } from '../src/pages/__tests__/scenarioSortingFixture';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';

const pairs = [
  ['Name', ['ALPHA', 'alpha', 'Zulu'], ['Zulu', 'ALPHA', 'alpha']],
  ['Prompt', ['ALPHA', 'alpha', 'Zulu'], ['Zulu', 'alpha', 'ALPHA']],
  ['Enabled', ['Zulu', 'ALPHA', 'alpha'], ['ALPHA', 'alpha', 'Zulu']],
] as const;

test('Scenario headers sort full prompt text and stable state locally while preserving the edited identity', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/eval-configs/suites/1', {
    ...suiteFixture(),
    scenarios: scenarioSortingRows,
  });
  fixtureAPI.mock(
    'PUT',
    '/api/eval-configs/scenarios/30',
    ({ request }: APIRequest) => ({
      ...scenarioSortingRows[0],
      ...request.postDataJSON(),
    }),
  );
  await page.goto('/eval-configs/1');
  const region = page.getByRole('region', {
    name: 'Suite scenarios',
    exact: true,
  });
  const names = () =>
    region
      .locator('tbody tr')
      .evaluateAll((rows) =>
        rows.map((row) => row.querySelector('td')!.textContent),
      );
  await expect.poll(names).toEqual(['Zulu', 'alpha', 'ALPHA']);
  const reads = fixtureAPI.requests.filter((entry) =>
    new URL(entry.url).pathname.startsWith('/api/'),
  ).length;
  for (const [label, ascending, descending] of pairs) {
    const header = region.getByRole('columnheader', {
      name: label,
      exact: true,
    });
    const button = header.getByRole('button');
    await button.focus();
    await button.press('Enter');
    await expect.poll(names).toEqual(ascending);
    await expect(header).toHaveAttribute('aria-sort', 'ascending');
    await button.press('Space');
    await expect.poll(names).toEqual(descending);
    await expect(header).toHaveAttribute('aria-sort', 'descending');
    await expect(button).toBeFocused();
  }
  expect(
    fixtureAPI.requests.filter((entry) =>
      new URL(entry.url).pathname.startsWith('/api/'),
    ),
  ).toHaveLength(reads);
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
  const row = region
    .getByRole('cell', { name: 'Zulu', exact: true })
    .locator('..');
  await row.getByRole('button', { name: 'Edit scenario', exact: true }).click();
  const editor = region
    .locator('tbody tr')
    .filter({ has: page.locator('textarea') });
  await editor.getByRole('textbox').first().fill('Unsaved Zulu draft');
  await editor
    .getByRole('textbox')
    .nth(1)
    .fill('Complete unsaved scenario prompt');
  await region.getByRole('button', { name: 'Name', exact: true }).click();
  await expect(editor.getByRole('textbox').first()).toHaveValue(
    'Unsaved Zulu draft',
  );
  await expect(editor.getByRole('textbox').nth(1)).toHaveValue(
    'Complete unsaved scenario prompt',
  );
  await editor.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(
    region.getByRole('cell', { name: 'Unsaved Zulu draft', exact: true }),
  ).toBeVisible();
  const writes = fixtureAPI.requests.filter((entry) => entry.method !== 'GET');
  expect(writes).toHaveLength(1);
  expect(new URL(writes[0].url).pathname).toBe(
    '/api/eval-configs/scenarios/30',
  );
});

for (const font of ['default', 'Arial']) {
  test(`Scenario headers and drafts remain readable at true 1x and 2x ${font} text`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    fixtureAPI.get('/api/eval-configs/suites/1', {
      ...suiteFixture(),
      scenarios: scenarioSortingRows,
    });
    await page.goto('/eval-configs/1');
    const region = page.getByRole('region', {
      name: 'Suite scenarios',
      exact: true,
    });
    await expect(region.getByRole('row')).toHaveCount(4);
    if (font === 'Arial')
      await page.addStyleTag({
        content: '* {font-family: Arial,sans-serif!important;}',
      });
    await expectSortableHeaderLayout(page, testInfo, {
      table: region.getByRole('table'),
      scrollRegion: region,
      labels: ['Name', 'Prompt', 'Enabled'],
      fullyVisibleHeaders: ['Name', 'Prompt', 'Enabled'],
      artifactPrefix: `scenario-headers-${font.toLowerCase()}`,
    });
  });
}

test('Empty scenario tables retain usable sort headers', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/eval-configs/suites/1', {
    ...suiteFixture(),
    scenarios: [],
  });
  await page.goto('/eval-configs/1');
  const region = page.getByRole('region', {
    name: 'Suite scenarios',
    exact: true,
  });
  await expect(region.getByRole('columnheader')).toHaveCount(4);
  for (const [label] of pairs) {
    const header = region.getByRole('columnheader', {
      name: label,
      exact: true,
    });
    await header.getByRole('button').click();
    await expect(header).toHaveAttribute('aria-sort', 'ascending');
    await header.getByRole('button').click();
    await expect(header).toHaveAttribute('aria-sort', 'descending');
  }
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});
