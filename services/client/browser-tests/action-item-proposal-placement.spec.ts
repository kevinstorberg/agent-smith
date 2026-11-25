import { chooseEpic, openEpicPicker, expectEpicSelection } from './epicPicker';
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
import type { Page } from '@playwright/test';

async function expectDecisionRows(page: Page) {
  const controls = page.locator('.action-item-proposal-decision-controls');
  const buttons = controls
    .locator('.action-item-proposal-decision-buttons')
    .getByRole('button');
  const [approve, reject] = await Promise.all([
    buttons.nth(0).boundingBox(),
    buttons.nth(1).boundingBox(),
  ]);
  expect(Math.abs(approve!.y - reject!.y)).toBeLessThanOrEqual(1);
  if (page.viewportSize()!.width <= 600) {
    const [select, container] = await Promise.all([
      controls.getByRole('button', { name: /Epic for/ }).boundingBox(),
      controls.boundingBox(),
    ]);
    expect(select!.width).toBeGreaterThanOrEqual(container!.width - 2);
    expect(approve!.y).toBeGreaterThanOrEqual(select!.y + select!.height);
  }
}

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
  const select = row.getByRole('button', { name: /Epic for/ });
  const options = await openEpicPicker(select);
  await expect(
    options.getByRole('button', { name: 'Release #10', exact: true }),
  ).toHaveCount(1);
  await chooseEpic(select, '10');
  await expectDecisionRows(page);
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
  await expectEpicSelection(select, 'Release #10 — earlier choice');
  await restore?.();
  restore = await enlargeComputedText(page, 2, { restorable: true });
  await expectDecisionRows(page);
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
  const select = page.getByRole('button', { name: /Epic for/ });
  const options = await openEpicPicker(select);
  await expect(
    options.getByRole('button', { name: destination.title, exact: true }),
  ).toHaveCount(1);
  await chooseEpic(select, '10');
  proposal = { ...proposal, current_parent: refreshedParent };
  epics = [refreshedDestination];
  await page.getByRole('button', { name: 'Refresh Epics' }).click();
  await expectEpicSelection(select, 'Release — earlier choice');
  await chooseEpic(select, '10');
  await expectEpicSelection(select, refreshedDestination.title);
  await page.screenshot({
    path: testInfo.outputPath('proposal-selected-epic-1x.png'),
    fullPage: true,
  });
  await enlargeComputedText(page);
  await expectDecisionRows(page);
  await expectControlContained(select, page.locator('#main-content'));
  await expectControlContained(
    page.getByRole('button', { name: 'Accept', exact: true }),
    page.locator('#main-content'),
  );
  await page.screenshot({
    path: testInfo.outputPath('proposal-selected-epic-2x.png'),
    fullPage: true,
  });
  expect(bodies).toEqual([]);
  await page.getByRole('button', { name: 'Accept', exact: true }).click();
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
    current_parent_title: 'Release',
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
    page
      .getByRole('button', { name: /Epic for/ })
      .locator(':scope > span')
      .first(),
  ).toHaveText('Release');
  await expect(
    page.getByRole('button', { name: 'Reject', exact: true }),
  ).toBeEnabled();
  await page.getByRole('button', { name: 'Accept', exact: true }).click();
  await expect(
    page.getByRole('link', { name: 'Open saved action item' }),
  ).toBeVisible();
  expect(bodies).toEqual([{}]);
  expect(
    fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
  ).toHaveLength(1);
});
