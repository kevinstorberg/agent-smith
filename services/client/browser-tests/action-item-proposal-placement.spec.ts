import { test, expect, type APIRequest } from './fixtures';
import { actionItemProposal } from '../src/pages/__tests__/actionItemProposalFixture';
import { epicGroup } from '../src/pages/__tests__/actionItemEpicFixture';
import { epicReference } from '../src/utils/actionItemEpics';
import { enlargeComputedText } from './typography';
import {
  expectControlContained,
  expectDocumentContained,
  expectMainContained,
} from './geometry';

test('list acceptance retains the chosen Epic receipt through refresh and an explicit retry', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  const destination = epicGroup(10, []).epic;
  const duplicate = { ...epicGroup(20, []).epic, title: destination.title };
  let epics = [destination, duplicate];
  let proposal = actionItemProposal({
    action: 'create',
    target_id: null,
    base_version: null,
    current_target: null,
    current_parent: null,
  });
  const bodies: unknown[] = [];
  fixtureAPI.get('/api/action-items/epics', () => ({ items: epics }));
  fixtureAPI.get('/api/action-item-proposals', () => ({
    items: proposal.status === 'pending' ? [proposal] : [],
    total: proposal.status === 'pending' ? 1 : 0,
  }));
  fixtureAPI.get('/api/action-item-proposals/counts', () => ({
    pending: proposal.status === 'pending' ? 1 : 0,
    approved: proposal.status === 'approved' ? 1 : 0,
    rejected: 0,
    superseded: 0,
  }));
  fixtureAPI.mock(
    'POST',
    '/api/action-item-proposals/1/approve',
    ({ request }: APIRequest) => {
      bodies.push(request.postDataJSON());
      return { detail: 'Uncertain response' };
    },
    503,
  );
  await page.goto('/action-items/proposals');
  const row = page.getByRole('listitem');
  const select = row.getByRole('combobox', { name: /Epic for/ });
  await expect(
    row.getByRole('option', { name: 'Release #10', exact: true }),
  ).toHaveCount(1);
  await select.selectOption('10');
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
  await page.screenshot({
    path: testInfo.outputPath('proposal-selected-epic-1x.png'),
    fullPage: true,
  });
  let restore = await enlargeComputedText(page, 2, { restorable: true });
  await expectControlContained(select, row);
  const accept = row.getByRole('button', { name: 'Accept', exact: true });
  await accept.click();
  await expect(page.getByRole('alert')).toContainText('Uncertain response');
  await expect(accept).toBeEnabled();
  await expect(accept).toBeFocused();
  epics = [
    {
      ...destination,
      title: 'Renamed release with supporting project context',
      revision: 9,
      cohort: 'fresh-destination',
    },
    duplicate,
  ];
  await page.getByRole('button', { name: 'Refresh Epics' }).click();
  await expect(select).toHaveValue('earlier');
  await expect(select.locator('option:checked')).toHaveText(
    'Release #10 — earlier choice',
  );
  await restore?.();
  restore = await enlargeComputedText(page, 2, { restorable: true });
  if (page.viewportSize()!.width > 600) {
    const heading = (await row
      .locator('.action-item-proposal-heading')
      .boundingBox())!;
    const identity = (await row
      .locator('.action-item-proposal-identity')
      .boundingBox())!;
    expect(identity.width).toBeGreaterThanOrEqual(heading.width * 0.45);
  }
  await expectControlContained(select, row);
  await page.screenshot({
    path: testInfo.outputPath('proposal-earlier-epic-2x.png'),
    fullPage: true,
  });
  fixtureAPI.mock(
    'POST',
    '/api/action-item-proposals/1/approve',
    ({ request }: APIRequest) => {
      bodies.push(request.postDataJSON());
      proposal = {
        ...proposal,
        status: 'approved',
        applied_ref: { action_item_id: 35 },
      };
      return proposal;
    },
  );
  await accept.click();
  await expect(
    page.getByRole('heading', { name: 'No pending proposed Action Items' }),
  ).toBeVisible();
  expect(bodies).toEqual([
    {
      placement: {
        expected_parent: null,
        destination: epicReference(destination),
      },
    },
    {
      placement: {
        expected_parent: null,
        destination: epicReference(destination),
      },
    },
  ]);
  expect(
    fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
  ).toHaveLength(2);
  await restore?.();
  restore = await enlargeComputedText(page, 2, { restorable: true });
  await expectDocumentContained(page);
  await expectMainContained(page);
  await restore?.();
});

test('detail acceptance uses fresh parent and destination only after explicit reselection', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  const destination = epicGroup(10, []).epic;
  const parent = epicReference(epicGroup(20, []).epic);
  const refreshedDestination = {
    ...destination,
    revision: 4,
    cohort: 'fresh-destination',
    title: 'Release delivery and supporting customer readiness',
  };
  const refreshedParent = {
    ...parent,
    expected_revision: 4,
    cohort: 'fresh-parent',
  };
  let proposal = actionItemProposal({ current_parent: parent });
  let epics = [destination];
  const bodies: unknown[] = [];
  fixtureAPI.get('/api/action-item-proposals/1', () => proposal);
  fixtureAPI.get('/api/action-items/epics', () => ({ items: epics }));
  fixtureAPI.mock(
    'POST',
    '/api/action-item-proposals/1/approve',
    ({ request }: APIRequest) => {
      bodies.push(request.postDataJSON());
      proposal = {
        ...proposal,
        status: 'approved',
        applied_ref: { action_item_id: 12 },
      };
      return proposal;
    },
  );
  await page.goto('/action-items/proposals/1');
  const select = page.getByRole('combobox', { name: /Epic for/ });
  await expect(
    page.getByRole('option', { name: destination.title, exact: true }),
  ).toHaveCount(1);
  await select.selectOption('10');
  proposal = { ...proposal, current_parent: refreshedParent };
  epics = [refreshedDestination];
  await page.getByRole('button', { name: 'Refresh Epics' }).click();
  await expect(select.locator('option:checked')).toHaveText(
    'Release — earlier choice',
  );
  await select.selectOption('10');
  await expect(select.locator('option:checked')).toHaveText(
    refreshedDestination.title,
  );
  await page.screenshot({
    path: testInfo.outputPath('proposal-selected-epic-1x.png'),
    fullPage: true,
  });
  await enlargeComputedText(page);
  await expectControlContained(select, page.locator('#main-content'));
  await expectControlContained(
    page.getByRole('button', { name: 'Approve', exact: true }),
    page.locator('#main-content'),
  );
  await page.screenshot({
    path: testInfo.outputPath('proposal-selected-epic-2x.png'),
    fullPage: true,
  });
  expect(bodies).toEqual([]);
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(
    page.getByRole('link', { name: 'Open saved action item' }),
  ).toHaveAttribute('href', '/action-items/12');
  expect(bodies).toEqual([
    {
      placement: {
        expected_parent: refreshedParent,
        destination: epicReference(refreshedDestination),
      },
    },
  ]);
  expect(
    fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
  ).toHaveLength(1);
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('an unavailable catalog leaves ordinary update acceptance and rejection independent of placement', async ({
  page,
  fixtureAPI,
}) => {
  let proposal = actionItemProposal({
    current_parent: epicReference(epicGroup(20, []).epic),
  });
  const bodies: unknown[] = [];
  fixtureAPI.get('/api/action-item-proposals/1', () => proposal);
  fixtureAPI.get(
    '/api/action-items/epics',
    { detail: 'Catalog unavailable' },
    503,
  );
  fixtureAPI.mock(
    'POST',
    '/api/action-item-proposals/1/approve',
    ({ request }: APIRequest) => {
      bodies.push(request.postDataJSON());
      proposal = {
        ...proposal,
        status: 'approved',
        applied_ref: { action_item_id: 12 },
      };
      return proposal;
    },
  );
  await page.goto('/action-items/proposals/1');
  await expect(page.getByRole('alert')).toContainText('Could not load Epics');
  await expect(
    page.getByRole('combobox', { name: /Epic for/ }).locator('option:checked'),
  ).toHaveText('Keep current Epic');
  await expect(
    page.getByRole('button', { name: 'Reject', exact: true }),
  ).toBeEnabled();
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(
    page.getByRole('link', { name: 'Open saved action item' }),
  ).toBeVisible();
  expect(bodies).toEqual([{}]);
  expect(
    fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
  ).toHaveLength(1);
});
