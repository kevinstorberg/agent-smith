import type { MemoryItem, Plan } from '../src/api';
import { MAX_NAME_LENGTH, MAX_TITLE_LENGTH } from '../src/constants';
import { harnessFixture } from './harnessFixture';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import { profileFixture } from '../src/pages/__tests__/profileFixture';
import { test, expect } from './fixtures';
import { expectControlContained, expectControlLabel, expectControlsUnclipped, expectDialogContained, expectDocumentContained, expectMainContained } from './geometry';

const stamp = '2026-11-03T12:00:00Z';
const longText = 'Review the release ownership, security decisions, and next steps with the engineering and product teams';

test('Memory checkbox remains labeled, operable, and contained beside text controls', async ({ page, fixtureAPI }, testInfo) => {
  const memory: MemoryItem = { id: 'browser-memory', content: longText, repo: 'browser-fixture', tags: ['release'], created_at: stamp };
  fixtureAPI.get('/api/memory/list', { items: [memory], total: 1 });
  await page.goto('/memory');
  await expect(page.getByText(longText, { exact: true })).toBeVisible();
  const checkbox = page.getByRole('checkbox', { name: 'Meetings only' });
  await expectControlLabel(checkbox, 'Meetings only');
  await expectControlContained(checkbox, page.locator('.memory-controls').nth(1));
  await expect(checkbox).not.toBeChecked();
  await page.getByText('Meetings only', { exact: true }).click();
  await expect(checkbox).toBeChecked();
  await expect.poll(() => fixtureAPI.requests.some(entry => new URL(entry.url).searchParams.get('meeting_only') === 'true')).toBe(true);
  await checkbox.focus();
  await page.keyboard.press('Space');
  await expect(checkbox).not.toBeChecked();
  await testInfo.attach('checkbox-geometry.json', { body: JSON.stringify(await checkbox.boundingBox()), contentType: 'application/json' });
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
});

test('Plans keep long titles and pagination inside the page', async ({ page, fixtureAPI }) => {
  const plan: Plan = { id: 1, title: `${longText} ${'long_identifier_'.repeat(8)}`.slice(0, MAX_TITLE_LENGTH), body: longText, project: 'browser-fixture', status: 'draft', created_at: stamp, updated_at: stamp };
  fixtureAPI.get('/api/plans', { items: [plan], total: 1 });
  await page.goto('/plans');
  await expect(page.getByRole('cell', { name: plan.title, exact: true })).toBeVisible();
  await expectControlLabel(page.getByRole('textbox', { name: 'Search plans' }), 'Search plans');
  await expectControlContained(page.getByRole('button', { name: '+ New Plan' }), page.locator('#main-content'));
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
});

test('Harness detail contains long Markdown without changing its padding', async ({ page, fixtureAPI }) => {
  const item = harnessFixture({ name: 'release_'.padEnd(MAX_NAME_LENGTH, 'x'),
    content: { body: `## Release review\n\n${longText}\n\n${longText}`, metadata: {} } });
  fixtureAPI.get('/api/harness/items/rule/1', item);
  fixtureAPI.get('/api/harness/items/rule/1/history', []);
  await page.goto('/harness/rule/1');
  await expect(page.getByRole('heading', { name: item.name, exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Release review', exact: true })).toBeVisible();
  const padding = await page.locator('.markdown-content').first().evaluate(element => {
    const style = getComputedStyle(element);
    return [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft];
  });
  expect(padding).toEqual(['16px', '16px', '16px', '16px']);
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
});

test('Discussion topic dialog keeps labels and actions reachable', async ({ page, fixtureAPI }) => {
  fixtureAPI.get(`/api/profiles/${profileFixture.id}`, profileFixture);
  fixtureAPI.get(`/api/profiles/${profileFixture.id}/discussion-topics`, { profile_id: profileFixture.id, items: [{ ...actionItem(1), profile_id: profileFixture.id }], total: 1 });
  await page.goto(`/profiles/${profileFixture.id}?tab=topics`);
  await page.getByRole('button', { name: 'New discussion topic' }).click();
  const dialog = page.getByRole('dialog', { name: 'New discussion topic' });
  await expectDialogContained(dialog);
  await expectControlLabel(dialog.getByRole('textbox', { name: 'Title', exact: true }), 'Title');
  const cancel = dialog.getByRole('button', { name: 'Cancel', exact: true });
  await cancel.scrollIntoViewIfNeeded();
  await expectControlContained(cancel, dialog);
  await cancel.click();
  await expect(dialog).not.toBeVisible();
  await expectDocumentContained(page);
  await expectMainContained(page);
});

test('Offline routing rejects unmatched APIs, external traffic, and writes', async ({ page, fixtureAPI, baseURL }) => {
  fixtureAPI.get('/api/memory/list', { items: [], total: 0 });
  for (const [method, url] of [
    ['GET', `${baseURL}/api/not-fixtured`],
    ['GET', 'https://never-contact.invalid/browser-proof'],
    ['POST', `${baseURL}/api/memory/list`],
  ]) {
    fixtureAPI.expectBlocked(method, url);
    const rejected = await page.evaluate(async ({ method, url }) => {
      try { await fetch(url, { method }); return false; }
      catch { return true; }
    }, { method, url });
    expect(rejected).toBe(true);
  }
});
