import { test, expect } from './fixtures';
import { expectDocumentContained, expectMainContained } from './geometry';
import { enlargeComputedText } from './typography';
import { actionItemProposal } from '../src/pages/__tests__/actionItemProposalFixture';

test('replaced Action Item proposals remain inspectable without decision controls', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  fixtureAPI.get('/api/action-items/epics', { items: [] });
  const replaced = actionItemProposal({
    status: 'superseded',
    superseded_by_id: 7,
  });
  const unavailable = actionItemProposal({
    id: 2,
    status: 'superseded',
    superseded_by_id: null,
  });
  fixtureAPI.get('/api/action-item-proposals', {
    items: [replaced, unavailable],
    total: 2,
  });
  fixtureAPI.get('/api/action-item-proposals/counts', {
    pending: 1,
    approved: 0,
    rejected: 0,
    superseded: 2,
  });
  fixtureAPI.get('/api/action-item-proposals/1', replaced);
  fixtureAPI.get('/api/action-item-proposals/7', actionItemProposal({ id: 7 }));
  await page.goto('/action-items/proposals?status=superseded');
  await expect(page.getByRole('combobox', { name: 'Status' })).toHaveValue(
    'superseded',
  );
  await expect(
    page.getByRole('option', { name: 'Superseded (2)' }),
  ).toHaveCount(1);
  await expect(
    page.getByRole('link', { name: 'View replacement' }),
  ).toHaveAttribute('href', '/action-items/proposals/7');
  await expect(
    page.getByText('Replacement unavailable.', { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: /^(Accept|Reject)$/ }),
  ).toHaveCount(0);
  await enlargeComputedText(page);
  await page.getByText('Details & evidence', { exact: true }).first().click();
  await expect(
    page.getByText(replaced.evidence[0].quote, { exact: true }).first(),
  ).toBeVisible();
  await expectDocumentContained(page);
  await expectMainContained(page);
  await page.screenshot({
    path: testInfo.outputPath('superseded-list.png'),
    fullPage: true,
  });
  await page.goto('/action-items/proposals/1');
  await expect(
    page.getByRole('link', { name: 'View replacement' }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: /^(Accept|Reject)$/ }),
  ).toHaveCount(0);
  await page.getByRole('link', { name: 'View replacement' }).click();
  await expect(
    page.getByRole('button', { name: 'Accept', exact: true }),
  ).toBeEnabled();
  expect(
    fixtureAPI.requests.filter((request) => request.method !== 'GET'),
  ).toEqual([]);
});
