import { test, expect, type APIRequest } from './fixtures';
import {
  expectControlContained,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { enlargeComputedText } from './typography';
import { actionItemProposal } from '../src/pages/__tests__/actionItemProposalFixture';
import { meetingFixture } from '../src/pages/__tests__/meetingFixture';
import { POLL_INTERVAL_MS } from '../src/constants';
import type {
  ActionItemProposal,
  MeetingActionItemProposals,
} from '../src/api';

test.beforeEach(({ fixtureAPI }) => {
  fixtureAPI.get('/api/action-items/epics', { items: [] });
});

test('an added description has explicit reviewed values before its placement and decision controls', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  const original = actionItemProposal();
  const before = {
    ...original.before_snapshot,
    title: 'Coordinate the partner meeting',
    description: '',
  };
  const description =
    'Schedule a technical call before Thursday and confirm how the partner will send the screening data.';
  const proposal = actionItemProposal({
    target_name: before.title,
    before_snapshot: before,
    current_target: before,
    proposed_item: { ...before, description },
  });
  fixtureAPI.get('/api/action-item-proposals', { items: [proposal], total: 1 });
  fixtureAPI.get('/api/action-item-proposals/counts', {
    pending: 1,
    approved: 0,
    rejected: 0,
    superseded: 0,
  });
  await page.goto('/action-items/proposals');
  const row = page
    .getByRole('list', { name: 'Proposed Action Items', exact: true })
    .getByRole('listitem');
  const field = row
    .getByRole('rowheader', { name: 'Description', exact: true })
    .locator('..');
  await expect(field.getByRole('cell').nth(0)).toHaveText('No description');
  await expect(field.getByRole('cell').nth(1)).toHaveText(description);
  await expect(row.getByRole('combobox', { name: /Epic for/ })).toHaveValue('');
  await expect(
    row.getByRole('combobox', { name: /Epic for/ }).locator('option:checked'),
  ).toHaveText('No Epic');
  for (const scale of [1, 2]) {
    if (scale === 2) await enlargeComputedText(page);
    const select = row.getByRole('combobox', { name: /Epic for/ });
    const accept = row.getByRole('button', { name: 'Accept', exact: true });
    const reject = row.getByRole('button', { name: 'Reject', exact: true });
    const [contentBox, selectBox, acceptBox, rejectBox] = await Promise.all([
      field.boundingBox(),
      select.boundingBox(),
      accept.boundingBox(),
      reject.boundingBox(),
    ]);
    expect(
      selectBox!.y,
      'Placement follows the full reviewed change',
    ).toBeGreaterThanOrEqual(contentBox!.y + contentBox!.height);
    expect(
      Math.abs(acceptBox!.y - rejectBox!.y),
      'Accept and Reject stay together',
    ).toBeLessThanOrEqual(1);
    for (const control of [select, accept, reject])
      await expectControlContained(control, row);
    await expectDocumentContained(page);
    await expectMainContained(page);
    await page.screenshot({
      path: testInfo.outputPath(`description-addition-${scale}x.png`),
      fullPage: true,
    });
  }
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

function compactCreateProposals(): ActionItemProposal[] {
  return [
    {
      title: 'Send the release report',
      description: `Send the report to the delivery team with the approved checklist.\n\n${'SupportingContext'.repeat(30)}`,
      due_at: '2026-11-25T17:00:00Z',
      status: 'open' as const,
    },
    {
      title: 'Schedule the launch review',
      description:
        'Find a time with the release team and circulate the agenda.',
      due_at: null,
      status: 'open' as const,
    },
    {
      title: 'Archive the approved checklist',
      description: 'Retain the final checklist in the release archive.',
      due_at: null,
      status: 'completed' as const,
    },
  ].map((item, index) =>
    actionItemProposal({
      id: index + 11,
      action: 'create',
      target_id: null,
      base_version: null,
      before_snapshot: null,
      current_target: null,
      target_name: item.title,
      rationale:
        'The planning summary explicitly supports this concrete next step.',
      proposed_item: { ...item, project: 'Work', tags: ['release'] },
      evidence: [
        {
          source: 'meeting',
          id: 'synthetic-planning',
          note: 'Release planning',
          quote: `The team agreed to: ${item.title}.`,
          revision: 1,
        },
      ],
    }),
  );
}

test('compact create rows expose decisions and keep complete context recoverable', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  const proposals = compactCreateProposals();
  fixtureAPI.get('/api/action-item-proposals', {
    items: proposals,
    total: proposals.length,
  });
  fixtureAPI.get('/api/action-item-proposals/counts', {
    pending: proposals.length,
    approved: 0,
    rejected: 0,
    superseded: 0,
  });
  await page.goto('/action-items/proposals');
  const rows = page
    .getByRole('list', { name: 'Proposed Action Items', exact: true })
    .getByRole('listitem');
  await expect(rows).toHaveCount(3);
  const thirdRowBounds = await rows.nth(2).boundingBox();
  await page.screenshot({
    path: testInfo.outputPath('compact-create-list.png'),
    fullPage: true,
  });
  await enlargeComputedText(page);
  await page.screenshot({
    path: testInfo.outputPath('compact-create-list-enlarged.png'),
    fullPage: true,
  });

  if (page.viewportSize()?.width === 1440) {
    expect(thirdRowBounds).not.toBeNull();
    expect(
      thirdRowBounds!.y + thirdRowBounds!.height,
      'Three representative create rows fit in the initial desktop viewport',
    ).toBeLessThanOrEqual(900);
  }
  for (let index = 0; index < proposals.length; index++) {
    const row = rows.nth(index);
    await expect(
      row.getByRole('link', {
        name: proposals[index].target_name,
        exact: true,
      }),
    ).toHaveCount(1);
    await expect(row.locator('details')).not.toHaveAttribute('open');
    await expect(
      row.locator('.action-item-proposal-description-preview'),
    ).toContainText(
      proposals[index].proposed_item!.description!.split('\n\n')[0],
    );
    await expect(
      row
        .locator('details')
        .getByText(proposals[index].proposed_item!.description!, {
          exact: true,
        }),
    ).not.toBeVisible();
    for (const name of ['Accept', 'Reject'])
      await expectControlContained(
        row.getByRole('button', { name, exact: true }),
        row,
      );
  }
  await expect(rows.first().locator('.action-item-proposal-due')).toContainText(
    'November 25, 2026',
  );
  await expect(rows.nth(2).getByText('Creates completed item')).toBeVisible();
  await expectDocumentContained(page);
  await expectMainContained(page);
  const summary = rows.first().locator('summary');
  await summary.focus();
  await page.keyboard.press('Enter');
  await expect(rows.first().locator('details')).toHaveAttribute('open');
  await expect(
    rows
      .first()
      .getByText(proposals[0].proposed_item!.description!, { exact: true }),
  ).toBeVisible();
  await expect(
    rows.first().getByRole('rowheader', { name: 'Title', exact: true }),
  ).toHaveCount(0);
  await expectDocumentContained(page);
  await expectMainContained(page);
  await page.screenshot({
    path: testInfo.outputPath('compact-create-details-enlarged.png'),
    fullPage: true,
  });
  await summary.focus();
  await page.keyboard.press('Space');
  await expect(rows.first().locator('details')).not.toHaveAttribute('open');
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('review failures have one persistent visible error and retain the pending row', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  await page.clock.install();
  const proposal = compactCreateProposals()[0];
  fixtureAPI.get('/api/action-item-proposals', { items: [proposal], total: 1 });
  fixtureAPI.get('/api/action-item-proposals/counts', {
    pending: 1,
    approved: 0,
    rejected: 0,
    superseded: 0,
  });
  fixtureAPI.mock(
    'POST',
    `/api/action-item-proposals/${proposal.id}/reject`,
    { detail: 'Synthetic review conflict' },
    409,
  );
  await page.goto('/action-items/proposals');
  await page.getByRole('button', { name: 'Reject', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveCount(1);
  await expect(page.getByRole('alert')).toContainText(
    'Synthetic review conflict',
  );
  await expect(page.getByText(/Synthetic review conflict/)).toHaveCount(1);
  await expect(
    page.getByRole('link', { name: proposal.target_name, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Reject', exact: true }),
  ).toBeEnabled();
  await page.clock.fastForward(POLL_INTERVAL_MS);
  await expect(page.getByText(/Synthetic review conflict/)).toHaveCount(1);
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [
      expect.objectContaining({
        method: 'POST',
        url: expect.stringContaining(
          `/action-item-proposals/${proposal.id}/reject`,
        ),
      }),
    ],
  );
  await expectDocumentContained(page);
  await page.screenshot({
    path: testInfo.outputPath('compact-review-error.png'),
    fullPage: true,
  });
});

test('supporting context stays open through a normal poll without submitting a decision', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  await page.clock.install();
  let reads = 0;
  const proposal = actionItemProposal();
  fixtureAPI.get('/api/action-item-proposals', () => ({
    items: [{ ...proposal, rationale: `Planning context read ${++reads}` }],
    total: 1,
  }));
  fixtureAPI.get('/api/action-item-proposals/counts', {
    pending: 1,
    approved: 0,
    rejected: 0,
    superseded: 0,
  });
  await page.goto('/action-items/proposals');
  const details = page
    .getByRole('list', { name: 'Proposed Action Items', exact: true })
    .locator('details');
  await details.locator('summary').click();
  await expect(page.getByText('Planning context read 1')).toBeVisible();
  await page.clock.fastForward(POLL_INTERVAL_MS);
  await expect.poll(() => reads).toBeGreaterThan(1);
  await expect(page.getByText(`Planning context read ${reads}`)).toBeVisible();
  await expect(details).toHaveAttribute('open');
  await expect(
    page.getByRole('rowheader', { name: 'Deadline', exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath('compact-update-details.png'),
    fullPage: true,
  });
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('accepts and rejects from the list without navigation or confirmation', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  let proposals = [
    actionItemProposal(),
    actionItemProposal({
      id: 2,
      action: 'create',
      target_id: null,
      base_version: null,
      before_snapshot: null,
      current_target: null,
    }),
  ];
  fixtureAPI.get('/api/action-item-proposals', () => ({
    items: proposals.filter((item) => item.status === 'pending'),
    total: proposals.filter((item) => item.status === 'pending').length,
  }));
  fixtureAPI.get('/api/action-item-proposals/counts', () => ({
    pending: proposals.filter((item) => item.status === 'pending').length,
    approved: proposals.filter((item) => item.status === 'approved').length,
    rejected: proposals.filter((item) => item.status === 'rejected').length,
    superseded: 0,
  }));
  for (const [id, action, status] of [
    [1, 'approve', 'approved'],
    [2, 'reject', 'rejected'],
  ] as const) {
    fixtureAPI.mock(
      'POST',
      `/api/action-item-proposals/${id}/${action}`,
      () => {
        proposals = proposals.map((item) =>
          item.id === id ? { ...item, status } : item,
        );
        return proposals.find((item) => item.id === id);
      },
    );
  }
  page.on('dialog', () => {
    throw new Error('Quick decisions must not require confirmation');
  });
  await page.goto('/action-items/proposals');
  const cards = page
    .getByRole('list', { name: 'Proposed Action Items', exact: true })
    .getByRole('listitem');
  await expect(cards).toHaveCount(2);
  await expect(
    cards.first().getByRole('rowheader', { name: 'Deadline' }),
  ).toBeVisible();
  await expect(
    cards
      .first()
      .getByText('Move the release report deadline to Friday at 5 PM UTC.'),
  ).not.toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath('compact-update-list.png'),
    fullPage: true,
  });
  await enlargeComputedText(page);
  for (const card of await cards.all()) {
    for (const name of ['Accept', 'Reject']) {
      await expectControlContained(
        card.getByRole('button', { name, exact: true }),
        card,
      );
    }
  }
  await expectDocumentContained(page);
  await testInfo.attach('action-item-quick-decisions.png', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });
  await page.screenshot({
    path: testInfo.outputPath('compact-update-list-enlarged.png'),
    fullPage: true,
  });
  await cards
    .first()
    .getByRole('button', { name: 'Accept', exact: true })
    .click();
  await expect(cards).toHaveCount(1);
  await expect(page.getByRole('option', { name: 'Approved (1)' })).toHaveCount(
    1,
  );
  await cards
    .first()
    .getByRole('button', { name: 'Reject', exact: true })
    .click();
  await expect(
    page.getByRole('heading', { name: 'No pending proposed Action Items' }),
  ).toBeVisible();
  await expect(page.getByRole('option', { name: 'Rejected (1)' })).toHaveCount(
    1,
  );
  expect(new URL(page.url()).pathname).toBe('/action-items/proposals');
  expect(
    fixtureAPI.requests
      .filter((entry) => entry.method !== 'GET')
      .map((entry) => new URL(entry.url).pathname),
  ).toEqual([
    '/api/action-item-proposals/1/approve',
    '/api/action-item-proposals/2/reject',
  ]);
});

test('proposed Action Items have a separate workspace list and review endpoint', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  const proposal = actionItemProposal();
  fixtureAPI.get('/api/action-item-proposals', { items: [proposal], total: 1 });
  fixtureAPI.get('/api/action-item-proposals/counts', {
    pending: 1,
    approved: 0,
    rejected: 0,
    superseded: 0,
  });
  fixtureAPI.get('/api/action-item-proposals/1', proposal);
  await page.goto('/action-items/proposals');
  await expect(
    page.getByRole('heading', { name: 'Proposed Action Items', exact: true }),
  ).toBeVisible();
  const navigation = page.getByRole('navigation', {
    name: 'Primary navigation',
  });
  if (
    await navigation
      .getByRole('button', { name: 'Menu', exact: true })
      .isVisible()
  ) {
    await navigation.getByRole('button', { name: 'Menu', exact: true }).click();
  }
  await expect(
    navigation.getByRole('link', {
      name: 'Proposed action items',
      exact: true,
    }),
  ).toHaveAttribute('aria-current', 'page');
  await expect(
    navigation.getByRole('link', { name: 'Action items', exact: true }),
  ).not.toHaveAttribute('aria-current', 'page');
  if (
    await navigation
      .getByRole('button', { name: 'Close menu', exact: true })
      .isVisible()
  ) {
    await navigation
      .getByRole('button', { name: 'Close menu', exact: true })
      .click();
  }
  await expect(page.getByRole('button', { name: 'Generate now' })).toHaveCount(
    0,
  );
  await enlargeComputedText(page);
  await expectDocumentContained(page);
  await expectMainContained(page);
  await testInfo.attach('proposed-action-items-list.png', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });
  await page
    .getByRole('link', { name: proposal.target_name, exact: true })
    .click();
  await expect(
    page.getByRole('region', { name: 'Proposed action item changes' }),
  ).toBeVisible();
  expect(
    fixtureAPI.requests.filter((entry) =>
      new URL(entry.url).pathname.startsWith('/api/proposals'),
    ),
  ).toEqual([]);
});

test('an empty Action Item review queue explains task generation without harness controls', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/action-item-proposals', { items: [], total: 0 });
  fixtureAPI.get('/api/action-item-proposals/counts', {
    pending: 0,
    approved: 0,
    rejected: 0,
    superseded: 0,
  });
  await page.goto('/action-items/proposals');
  await expect(
    page.getByRole('heading', { name: 'No pending proposed Action Items' }),
  ).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Open meetings', exact: true }),
  ).toHaveAttribute('href', '/meetings');
  await expect(page.getByRole('button', { name: 'Generate now' })).toHaveCount(
    0,
  );
  await expectDocumentContained(page);
});

test('meeting proposal evidence and reviewed fields lead to one explicit approval', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  let proposal = actionItemProposal();
  fixtureAPI.get('/api/action-item-proposals/1', () => proposal);
  fixtureAPI.mock('POST', '/api/action-item-proposals/1/approve', () => {
    proposal = {
      ...proposal,
      status: 'approved',
      applied_ref: { action_item_id: 12 },
    };
    return proposal;
  });
  await page.goto('/action-items/proposals/1');
  const changes = page.getByRole('region', {
    name: 'Proposed action item changes',
  });
  await expect(
    changes.getByRole('rowheader', { name: 'Deadline' }),
  ).toBeVisible();
  await expect(changes.getByText(/November 18, 2026/)).toBeVisible();
  await expect(changes.getByText(/November 20, 2026/)).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Release planning' }),
  ).toHaveAttribute('href', '/meetings/meeting-123');
  await expect(
    page.getByText('Move the release report deadline to Friday at 5 PM UTC.'),
  ).toBeVisible();
  await enlargeComputedText(page);
  await expectControlContained(changes.getByText(/November 20, 2026/), changes);
  await expectDocumentContained(page);
  await expectMainContained(page);
  await testInfo.attach('meeting-action-item-review.png', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });
  await page.getByRole('button', { name: 'Accept', exact: true }).click();
  await expect(
    page.getByRole('link', { name: 'Open saved action item' }),
  ).toHaveAttribute('href', '/action-items/12');
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [
      expect.objectContaining({
        method: 'POST',
        url: expect.stringMatching(/\/api\/action-item-proposals\/1\/approve$/),
      }),
    ],
  );
});

test('rejecting a new task proposal never writes an action item', async ({
  page,
  fixtureAPI,
}) => {
  let proposal = actionItemProposal({
    action: 'create',
    target_id: null,
    base_version: null,
    before_snapshot: null,
    current_target: null,
  });
  fixtureAPI.get('/api/action-item-proposals/1', () => proposal);
  fixtureAPI.mock('POST', '/api/action-item-proposals/1/reject', () => {
    proposal = { ...proposal, status: 'rejected' };
    return proposal;
  });
  await page.goto('/action-items/proposals/1');
  const content = page.getByRole('region', {
    name: 'Proposed action item',
    exact: true,
  });
  await expect(content.getByText('Send the release report')).toBeVisible();
  await expect(
    content.getByRole('columnheader', { name: 'Before' }),
  ).toHaveCount(0);
  await page.getByRole('button', { name: 'Reject', exact: true }).click();
  await expect(page.getByText('rejected', { exact: true })).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Accept', exact: true }),
  ).toHaveCount(0);
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [
      expect.objectContaining({
        method: 'POST',
        url: expect.stringMatching(/\/api\/action-item-proposals\/1\/reject$/),
      }),
    ],
  );
});

test('stale task proposals preserve their reviewed comparison and block approval', async ({
  page,
  fixtureAPI,
}) => {
  const proposal = actionItemProposal();
  fixtureAPI.get('/api/action-item-proposals/1', {
    ...proposal,
    current_target: {
      ...proposal.current_target,
      revision: 4,
      due_at: '2026-12-01T17:00:00Z',
    },
  });
  await page.goto('/action-items/proposals/1');
  await expect(page.getByRole('alert')).toContainText(
    'This action item changed',
  );
  await expect(
    page.getByRole('button', { name: 'Accept', exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole('button', { name: 'Reject', exact: true }),
  ).toBeEnabled();
  const changes = page.getByRole('region', {
    name: 'Proposed action item changes',
  });
  await expect(changes.getByText(/November 18, 2026/)).toBeVisible();
  await expect(changes.getByText(/December 1, 2026/)).toHaveCount(0);
  await page.getByText('Current saved action item', { exact: true }).click();
  await expect(
    page
      .getByRole('region', { name: 'Current saved action item' })
      .getByText(/December 1, 2026/),
  ).toBeVisible();
  await expectDocumentContained(page);
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

test('a meeting queues proposal generation using its reviewed revision without changing tasks', async ({
  page,
  fixtureAPI,
}) => {
  const path = `/api/meetings/${meetingFixture.id}`;
  let state: MeetingActionItemProposals = {
    status: 'not_queued',
    error_type: null,
    proposal_count: 0,
    attempts: 0,
    next_attempt_at: null,
    worker_available: true,
  };
  const done = { status: 'done', reason: null, error_type: null };
  fixtureAPI.get(path, meetingFixture);
  fixtureAPI.get(`${path}/processing`, () => ({
    transcript: {
      status: 'ready',
      total: 0,
      error_type: null,
      captured_at: null,
    },
    memories: done,
    profiles: done,
    speakers: { status: 'not_imported', error_type: null },
    edit_lock_reason: null,
    action_item_proposals: state,
  }));
  fixtureAPI.mock(
    'POST',
    `${path}/action-item-proposals`,
    ({ request }: APIRequest) => {
      expect(request.postDataJSON()).toEqual({
        expected_revision: meetingFixture.revision,
      });
      state = { ...state, status: 'pending' };
      return state;
    },
    202,
  );
  await page.goto(`/meetings/${meetingFixture.id}?tab=overview`);
  const proposals = page.getByRole('region', {
    name: 'Proposed Action Items',
    exact: true,
  });
  await proposals
    .getByRole('button', { name: 'Propose action items', exact: true })
    .click();
  await expect(proposals.getByRole('status')).toContainText(
    'Action items stay unchanged until you approve.',
  );
  await expect(
    proposals.getByRole('button', { name: 'Generating proposals…' }),
  ).toBeDisabled();
  await expect(
    proposals.getByRole('link', { name: 'Review proposed action items' }),
  ).toHaveAttribute('href', '/action-items/proposals?status=pending');
  await expectDocumentContained(page);
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [
      expect.objectContaining({
        method: 'POST',
        url: expect.stringMatching(/\/action-item-proposals$/),
      }),
    ],
  );
});
