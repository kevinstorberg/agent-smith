import type { Locator } from '@playwright/test';
import type { Plan, ProfileRevision } from '../src/api';
import { profileFixture } from '../src/pages/__tests__/profileFixture';
import { chatDetail, chatMessage, chatRoom } from './chatFixture';
import { test, expect, type APIRequest } from './fixtures';
import { expectControlContained, expectControlReachable, expectDocumentContained, expectMainContained } from './geometry';
import { meetingAnalysisCandidatesPage } from './meetingAnalysisFixture';
import { enlargeComputedText } from './typography';

function pageData<T>(url: URL, total: number, item: (index: number) => T) {
  const limit = Number(url.searchParams.get('limit') || 10);
  const offset = Number(url.searchParams.get('offset') || 0);
  return { total, items: Array.from({ length: Math.min(limit, Math.max(0, total - offset)) }, (_, index) => item(offset + index)) };
}

function chatResponses(register: (path: string, response: unknown) => void, total: number) {
  register('/api/chat', ({ url }: APIRequest) => pageData(url, total, index => chatRoom({ id: index + 1, topic: `Release planning ${index + 1}` })));
  register('/api/chat/config', { participants: ['synthetic-agent'] });
  register('/api/chat/1', chatDetail(chatRoom({ topic: 'Release planning 1' }), [chatMessage(1)]));
}

async function expectReadablePagination(pager: Locator, container: Locator) {
  await expect(pager).toBeVisible();
  for (const control of await pager.getByRole('button').all()) {
    if (!await control.isVisible()) continue;
    await expectControlReachable(control);
    await expectControlContained(control, container);
    const label = await control.evaluate(element => {
      const bounds = element.getBoundingClientRect();
      const range = document.createRange(); range.selectNodeContents(element);
      const lines = [...range.getClientRects()];
      return { text: element.textContent, size: parseFloat(getComputedStyle(element).fontSize),
        count: new Set(lines.map(rect => Math.round(rect.top * 2))).size,
        fits: lines.every(rect => rect.left >= bounds.left && rect.right <= bounds.right) };
    });
    expect(label.size).toBeGreaterThanOrEqual(13);
    expect(label.count, `${label.text} must remain one full readable line`).toBe(1);
    expect(label.fits, `${label.text} must fit inside its button`).toBe(true);
  }
  for (const label of await pager.locator('.pagination-info, .pagination-position, .pagination-page-size > span').all()) {
    if (!await label.isVisible()) continue;
    await label.evaluate(element => element.scrollIntoView({ block: 'center', inline: 'nearest' }));
    const text = await label.evaluate(element => {
      const bounds = element.getBoundingClientRect();
      const range = document.createRange(); range.selectNodeContents(element);
      const lines = [...range.getClientRects()];
      return { label: element.textContent,
        fits: lines.every(rect => rect.left >= bounds.left && rect.right <= bounds.right),
        unclipped: lines.every(rect => {
          for (let parent = element.parentElement; parent; parent = parent.parentElement) {
            if (!['auto', 'scroll', 'hidden', 'clip'].includes(getComputedStyle(parent).overflowY)) continue;
            const bounds = parent.getBoundingClientRect();
            if (rect.top < bounds.top + parent.clientTop || rect.bottom > bounds.top + parent.clientTop + parent.clientHeight) return false;
          }
          return true;
        }) };
    });
    expect(text.fits, `${text.label} must show its full text`).toBe(true);
    expect(text.unclipped, `${text.label} must scroll fully into its visible panel`).toBe(true);
  }
  const size = pager.getByRole('combobox', { name: 'Rows per page', exact: true });
  if (await size.count()) {
    await expectControlReachable(size);
    await expectControlContained(size, container);
    const selection = await size.evaluate(element => {
      const select = element as HTMLSelectElement;
      const style = getComputedStyle(select);
      const context = document.createElement('canvas').getContext('2d')!;
      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      return { width: context.measureText(select.selectedOptions[0].text).width,
        available: select.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) };
    });
    expect(selection.width, 'The full selected page size must remain readable').toBeLessThanOrEqual(selection.available);
  }
  await expectDocumentContained(pager.page());
  await expectMainContained(pager.page());
}

for (const scale of [1, 2]) {
  test(`Single-page Chat keeps only its range and page size at ${scale}× computed text`, async ({ page, fixtureAPI }, testInfo) => {
    chatResponses(fixtureAPI.get, 5);
    await page.goto('/chat');
    const rooms = page.getByRole('complementary', { name: 'Chat rooms', exact: true });
    const pager = rooms.getByRole('navigation', { name: 'Pagination', exact: true });
    await expect(pager).toContainText('Showing 1–5 of 5');
    if (scale !== 1) await enlargeComputedText(page, scale);
    await expect(pager.getByRole('button')).toHaveCount(0);
    await expectReadablePagination(pager, rooms);
    await testInfo.attach('single-page-chat.png', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
    await pager.getByRole('combobox', { name: 'Rows per page' }).selectOption('25');
    await expect.poll(() => fixtureAPI.requests.some(entry => {
      const url = new URL(entry.url);
      return url.pathname === '/api/chat' && url.searchParams.get('limit') === '25' && url.searchParams.get('offset') === '0';
    })).toBe(true);
    await expect(pager).toContainText('Showing 1–5 of 5');
  });

  test(`Narrow Chat retains usable first, middle, and last pages at ${scale}× computed text`, async ({ page, fixtureAPI }, testInfo) => {
    await page.setViewportSize({ width: page.viewportSize()!.width, height: 500 });
    chatResponses(fixtureAPI.get, 27);
    await page.goto('/chat');
    const rooms = page.getByRole('complementary', { name: 'Chat rooms', exact: true });
    const pager = rooms.getByRole('navigation', { name: 'Pagination', exact: true });
    const next = pager.getByRole('button', { name: 'Next', exact: true });
    const previous = pager.getByRole('button', { name: 'Previous', exact: true });
    await expect(next).toBeEnabled();
    if (scale !== 1) await enlargeComputedText(page, scale);
    await expect(pager.locator('.pagination-position')).toHaveText('Page 1 of 3');
    await expect(pager.locator('.pagination-position')).toBeVisible();
    await expect(previous).toBeDisabled();
    await expectReadablePagination(pager, rooms);
    await expectControlReachable(next);
    await next.focus();
    await next.press('Enter');
    await expect(pager).toContainText('Showing 11–20 of 27');
    await expect(next).toBeEnabled();
    await expectReadablePagination(pager, rooms);
    await expectControlReachable(next);
    await next.click();
    await expect(pager).toContainText('Showing 21–27 of 27');
    await expect(next).toBeDisabled();
    await expectReadablePagination(pager, rooms);
    await rooms.evaluate(element => { element.scrollTop = element.scrollHeight; });
    await expectControlReachable(next);
    await testInfo.attach('multi-page-chat.png', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
    await expectControlReachable(previous);
    await previous.click();
    await expect(pager).toContainText('Showing 11–20 of 27');
    await expect(pager.getByRole('combobox', { name: 'Rows per page' })).toBeEnabled();
    await pager.getByRole('combobox', { name: 'Rows per page' }).selectOption('25');
    await expect(pager).toContainText('Showing 1–25 of 27');
  });

  test(`Full-page tables retain direct page targets when space permits at ${scale}× computed text`, async ({ page, fixtureAPI }) => {
    fixtureAPI.get('/api/plans', ({ url }: APIRequest) => pageData<Plan>(url, 1000, index => ({ id: index + 1,
      title: `Release planning ${index + 1}`, body: 'A bounded plan.', project: 'browser-fixture', status: 'draft',
      created_at: '2026-11-03T12:00:00Z', updated_at: '2026-11-03T12:00:00Z' })));
    await page.goto('/plans?offset=490');
    const pager = page.getByRole('navigation', { name: 'Pagination', exact: true });
    await expect(pager).toContainText('Showing 491–500 of 1000');
    if (scale !== 1) await enlargeComputedText(page, scale);
    await expectReadablePagination(pager, page.locator('#main-content'));
    const last = pager.getByRole('button', { name: '100', exact: true });
    if (await last.isVisible()) {
      await last.click();
      await expect(pager).toContainText('Showing 991–1000 of 1000');
    } else {
      await expect(pager.locator('.pagination-position')).toBeVisible();
      await pager.getByRole('button', { name: 'Next', exact: true }).click();
      await expect(pager).toContainText('Showing 501–510 of 1000');
    }
  });

  test(`Analysis modal keeps its fixed page size and navigation at ${scale}× computed text`, async ({ page, fixtureAPI }) => {
    fixtureAPI.get(`/api/profiles/${profileFixture.id}`, profileFixture);
    fixtureAPI.get('/api/meeting-analysis/candidates', ({ url }: APIRequest) => meetingAnalysisCandidatesPage(url));
    await page.goto(`/profiles/${profileFixture.id}`);
    await page.getByRole('button', { name: 'Review past meetings', exact: true }).click();
    const dialog = page.getByRole('dialog');
    const pager = dialog.getByRole('navigation', { name: 'Pagination', exact: true });
    await expect(pager).toContainText('Showing 1–10 of 27');
    if (scale !== 1) await enlargeComputedText(page, scale);
    await expect(pager.getByRole('combobox')).toHaveCount(0);
    await expectReadablePagination(pager, dialog);
    const next = pager.getByRole('button', { name: 'Next', exact: true });
    await expectControlReachable(next);
    await next.click();
    await expect(pager).toContainText('Showing 11–20 of 27');
    await expect.poll(() => fixtureAPI.requests.some(entry => {
      const url = new URL(entry.url);
      return url.pathname === '/api/meeting-analysis/candidates' && url.searchParams.get('limit') === '10' && url.searchParams.get('offset') === '10';
    })).toBe(true);
  });

  test(`Nested History preserves adjustable pagination at ${scale}× computed text`, async ({ page, fixtureAPI }) => {
    fixtureAPI.get(`/api/profiles/${profileFixture.id}`, profileFixture);
    fixtureAPI.get(`/api/profiles/${profileFixture.id}/history`, ({ url }: APIRequest) => pageData<ProfileRevision>(url, 27, index => ({
      id: index + 1, profile_id: profileFixture.id, base_revision: index + 1, new_revision: index + 2,
      actor: 'human', source: 'manual', source_id: null, input_hash: null, created_at: profileFixture.updated_at, changes: {},
    })));
    await page.goto(`/profiles/${profileFixture.id}`);
    await page.getByText('History', { exact: true }).click();
    const history = page.locator('details').filter({ has: page.getByText('History', { exact: true }) });
    const pager = history.getByRole('navigation', { name: 'Pagination', exact: true });
    await expect(pager).toContainText('Showing 1–10 of 27');
    if (scale !== 1) await enlargeComputedText(page, scale);
    await expectReadablePagination(pager, history);
    await pager.getByRole('combobox', { name: 'Rows per page' }).selectOption('25');
    await expect(pager).toContainText('Showing 1–25 of 27');
  });

  test(`Evidence retains its fixed twenty-row page size at ${scale}× computed text`, async ({ page, fixtureAPI }) => {
    fixtureAPI.get(`/api/profiles/${profileFixture.id}`, profileFixture);
    fixtureAPI.get(`/api/profiles/${profileFixture.id}/claims`, ({ url }: APIRequest) => ({
      ...pageData(url, 45, index => ({ ...profileFixture.claims[0], id: `observation-${index + 1}` })),
      profile_id: profileFixture.id, revision: profileFixture.revision,
    }));
    await page.goto(`/profiles/${profileFixture.id}?tab=evidence`);
    const pager = page.getByRole('navigation', { name: 'Pagination', exact: true });
    await expect(pager).toContainText('Showing 1–20 of 45');
    if (scale !== 1) await enlargeComputedText(page, scale);
    await expect(pager.getByRole('combobox')).toHaveCount(0);
    await expectReadablePagination(pager, page.locator('#main-content'));
    await pager.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(pager).toContainText('Showing 21–40 of 45');
    await expect.poll(() => fixtureAPI.requests.some(entry => {
      const url = new URL(entry.url);
      return url.pathname.endsWith('/claims') && url.searchParams.get('limit') === '20' && url.searchParams.get('offset') === '20';
    })).toBe(true);
  });
}

test('Empty Chat has no pager and an in-flight page change locks every control', async ({ page, fixtureAPI }) => {
  chatResponses(fixtureAPI.get, 0);
  await page.goto('/chat');
  await expect(page.getByText('No rooms yet.', { exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Pagination', exact: true })).toHaveCount(0);
  let release: ((response: unknown) => void) | undefined;
  fixtureAPI.get('/api/chat', ({ url }: APIRequest) => Number(url.searchParams.get('offset')) === 10
    ? new Promise(resolve => { release = resolve; })
    : pageData(url, 27, index => chatRoom({ id: index + 1, topic: `Release planning ${index + 1}` })));
  await page.reload();
  const pager = page.getByRole('navigation', { name: 'Pagination', exact: true });
  await pager.getByRole('button', { name: 'Next', exact: true }).click();
  await expect.poll(() => Boolean(release)).toBe(true);
  for (const control of await pager.getByRole('button').all()) await expect(control).toBeDisabled();
  await expect(pager.getByRole('combobox')).toBeDisabled();
  release!(pageData(new URL('http://fixture.test/?limit=10&offset=10'), 27, index => chatRoom({ id: index + 1, topic: `Release planning ${index + 1}` })));
  await expect(pager.getByRole('button', { name: 'Next', exact: true })).toBeEnabled();
  await expect(pager).toContainText('Showing 11–20 of 27');
});
