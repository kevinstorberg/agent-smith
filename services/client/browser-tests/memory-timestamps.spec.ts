import type { MemoryItem } from '../src/api';
import { test, expect } from './fixtures';
import { expectControlContained, expectDocumentContained, expectMainContained } from './geometry';

test.use({ timezoneId: 'America/New_York', locale: 'en-US' });

const seasons = [
  {
    name: 'winter',
    created: '2026-01-15T14:05:06+00:00',
    accessed: '2026-01-16T01:15:00+00:00',
    localCreated: '1/15/2026, 9:05:06 AM',
    localAccessed: '1/15/2026, 8:15:00 PM',
  },
  {
    name: 'summer',
    created: '2026-07-15T14:05:06+00:00',
    accessed: '2026-07-16T01:15:00+00:00',
    localCreated: '7/15/2026, 10:05:06 AM',
    localAccessed: '7/15/2026, 9:15:00 PM',
  },
];

for (const season of seasons) {
  test(`Memory displays ${season.name} UTC timestamps in local time`, async ({ page, fixtureAPI }) => {
    const memory: MemoryItem = {
      id: 'dated-memory', content: 'Memory with UTC timestamps', repo: 'browser-fixture', tags: ['review'],
      created_at: season.created, last_accessed_at: season.accessed,
    };
    const undated: MemoryItem = {
      id: 'undated-memory', content: 'Memory without timestamp metadata', created_at: null, last_accessed_at: null,
    };
    fixtureAPI.get('/api/memory/list', { items: [memory, undated], total: 2 });

    await page.goto('/memory');
    const card = page.locator('.card').filter({ hasText: memory.content });
    const created = card.locator('time').nth(0);
    const accessed = card.locator('time').nth(1);
    await expect(created).toHaveText(season.localCreated);
    await expect(accessed).toHaveText(season.localAccessed);
    await expect(created).toHaveAttribute('datetime', season.created);
    await expect(accessed).toHaveAttribute('datetime', season.accessed);
    await expect(card.getByText(`Created: ${season.localCreated}`, { exact: true })).toBeVisible();
    await expect(card.getByText(`Last accessed: ${season.localAccessed}`, { exact: true })).toBeVisible();
    await expectControlContained(created, card);
    await expectControlContained(accessed, card);

    const undatedCard = page.locator('.card').filter({ hasText: undated.content });
    await expect(undatedCard.getByText('Created: Unavailable', { exact: true })).toBeVisible();
    await expect(undatedCard.getByText('Last accessed: Unavailable', { exact: true })).toBeVisible();
    await expect(undatedCard.locator('time')).toHaveCount(0);
    await expectDocumentContained(page);
    await expectMainContained(page);
  });
}
