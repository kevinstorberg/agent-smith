import { test, expect, type APIRequest } from './fixtures';
import {
  expectControlContained,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { enlargeComputedText } from './typography';
import { actionItemProposal } from '../src/pages/__tests__/actionItemProposalFixture';
import { meetingFixture } from '../src/pages/__tests__/meetingFixture';
import type { MeetingActionItemProposals } from '../src/api';

test('meeting proposal evidence and reviewed fields lead to one explicit approval', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  let proposal = actionItemProposal();
  fixtureAPI.get('/api/proposals/1', () => proposal);
  fixtureAPI.mock('POST', '/api/proposals/1/approve', () => {
    proposal = {
      ...proposal,
      status: 'approved',
      applied_ref: { action_item_id: 12 },
    };
    return proposal;
  });
  await page.goto('/proposals/1');
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
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(
    page.getByRole('link', { name: 'Open saved action item' }),
  ).toHaveAttribute('href', '/action-items/12');
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [
      expect.objectContaining({
        method: 'POST',
        url: expect.stringMatching(/\/api\/proposals\/1\/approve$/),
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
  fixtureAPI.get('/api/proposals/1', () => proposal);
  fixtureAPI.mock('POST', '/api/proposals/1/reject', () => {
    proposal = { ...proposal, status: 'rejected' };
    return proposal;
  });
  await page.goto('/proposals/1');
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
    page.getByRole('button', { name: 'Approve', exact: true }),
  ).toHaveCount(0);
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [
      expect.objectContaining({
        method: 'POST',
        url: expect.stringMatching(/\/api\/proposals\/1\/reject$/),
      }),
    ],
  );
});

test('stale task proposals preserve their reviewed comparison and block approval', async ({
  page,
  fixtureAPI,
}) => {
  const proposal = actionItemProposal();
  fixtureAPI.get('/api/proposals/1', {
    ...proposal,
    current_target: {
      ...proposal.current_target,
      revision: 4,
      due_at: '2026-12-01T17:00:00Z',
    },
  });
  await page.goto('/proposals/1');
  await expect(page.getByRole('alert')).toContainText(
    'This action item changed',
  );
  await expect(
    page.getByRole('button', { name: 'Approve', exact: true }),
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
    name: 'Action item proposals',
    exact: true,
  });
  await proposals
    .getByRole('button', { name: 'Generate proposals', exact: true })
    .click();
  await expect(proposals.getByRole('status')).toContainText(
    'Action items stay unchanged until you approve.',
  );
  await expect(
    proposals.getByRole('button', { name: 'Generating proposals…' }),
  ).toBeDisabled();
  await expect(
    proposals.getByRole('link', { name: 'Review proposals' }),
  ).toHaveAttribute('href', '/proposals?status=pending');
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
