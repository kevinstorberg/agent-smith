import { test, expect, type APIRequest } from './fixtures';
import type { ActionItemEpic } from '../src/api';
import { epicGroup } from '../src/pages/__tests__/actionItemEpicFixture';
import { enlargeComputedText } from './typography';
import { expectDocumentContained, expectMainContained } from './geometry';

const epic = (
  id: number,
  title: string,
  open: number,
  total: number,
): ActionItemEpic => ({
  ...epicGroup(id, []).epic,
  title,
  open_count: open,
  total_count: total,
});

for (const scale of [1, 2]) {
  test(`Manage Epics is independent of task filters and deletes only after explicit confirmation at ${scale}x text`, async ({
    page,
    fixtureAPI,
  }, info) => {
    let epics = [
      epic(10, 'Empty planning', 0, 0),
      epic(20, 'Completed clinical integration and partner readiness', 0, 4),
      epic(30, 'Current delivery', 2, 5),
    ];
    const writes: unknown[] = [];
    fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
    fixtureAPI.get('/api/action-items/queue', {
      items: [],
      total: 0,
      matching_count: 0,
    });
    fixtureAPI.get('/api/action-items/epics', ({ url }: APIRequest) => {
      expect([...url.searchParams]).toEqual([]);
      return { items: epics };
    });
    fixtureAPI.mock(
      'DELETE',
      '/api/action-items/epics/20',
      ({ request }: APIRequest) => {
        writes.push(request.postDataJSON());
        epics = epics.filter((entry) => entry.id !== 20);
        return { deleted: true, id: 20 };
      },
    );
    await page.goto(
      '/action-items?status=completed&project=Other&q=missing&tags=hidden',
    );
    await page.getByRole('link', { name: 'Manage Epics', exact: true }).click();
    await expect(page).toHaveURL(/\/action-items\/epics$/);
    await expect(
      page.getByText('Empty planning', { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText('Completed clinical integration and partner readiness', {
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByText('Current delivery', { exact: true }),
    ).toBeVisible();
    if (scale === 2) await enlargeComputedText(page);
    const headerLines = await page
      .getByRole('columnheader')
      .evaluateAll((headers) =>
        headers.map((header) => {
          const range = document.createRange();
          range.selectNodeContents(header);
          return range.getClientRects().length;
        }),
      );
    expect(headerLines).toEqual([1, 1, 1, 1, 1]);
    await expectDocumentContained(page);
    await expectMainContained(page);
    await page.screenshot({
      path: info.outputPath(`epic-manager-${scale}x.png`),
      fullPage: true,
    });
    const queueReads = fixtureAPI.requests.filter(
      (entry) => new URL(entry.url).pathname === '/api/action-items/queue',
    ).length;
    const search = page.getByRole('textbox', { name: 'Search Epics' });
    await search.fill('COMPLETED');
    await expect(page.getByText('Showing 1 of 3 Epics')).toBeVisible();
    const remove = page.getByRole('button', {
      name: 'Delete Epic Completed clinical integration and partner readiness',
      exact: true,
    });
    page.once('dialog', async (dialog) => {
      expect(dialog.message()).toContain(
        'Its action items will be kept and moved out',
      );
      await dialog.dismiss();
    });
    await remove.click();
    expect(writes).toEqual([]);
    page.once('dialog', (dialog) => dialog.accept());
    await remove.click();
    await expect.poll(() => writes.length).toBe(1);
    expect(writes).toEqual([{ expected_revision: 3, cohort: 'cohort-20' }]);
    await expect(page.getByText('No Epics match your search.')).toBeVisible();
    await search.fill('');
    await expect(page.getByText('Showing 2 of 2 Epics')).toBeVisible();
    expect(
      fixtureAPI.requests.filter(
        (entry) => new URL(entry.url).pathname === '/api/action-items/queue',
      ),
    ).toHaveLength(queueReads);
    expect(
      fixtureAPI.requests.filter((entry) => entry.method !== 'GET'),
    ).toHaveLength(1);
  });

  test(`Epic management renames and requires a fresh explicit delete after conflict at ${scale}x text`, async ({
    page,
    fixtureAPI,
  }, info) => {
    let epics = [epic(10, 'Release', 1, 5), epic(20, 'Release', 0, 0)];
    const renames: unknown[] = [];
    const deletes: unknown[] = [];
    fixtureAPI.get('/api/action-items/epics', () => ({ items: epics }));
    fixtureAPI.mock(
      'PATCH',
      '/api/action-items/epics/10',
      ({ request }: APIRequest) => {
        renames.push(request.postDataJSON());
        epics = epics.map((entry) =>
          entry.id === 10
            ? { ...entry, title: 'Reviewed release', revision: 4 }
            : entry,
        );
        return epics[0];
      },
    );
    fixtureAPI.mock(
      'DELETE',
      '/api/action-items/epics/10',
      ({ request }: APIRequest) => {
        deletes.push(request.postDataJSON());
        epics = epics.map((entry) =>
          entry.id === 10
            ? {
                ...entry,
                revision: 5,
                cohort: 'cohort-hidden-completed-change',
                total_count: 6,
              }
            : entry,
        );
        return { detail: 'Epic membership changed. Review the current Epic.' };
      },
      409,
    );
    await page.goto('/action-items/epics');
    await page
      .getByRole('button', { name: 'Rename Epic Release #10', exact: true })
      .click();
    const name = page.getByRole('textbox', { name: 'Epic name', exact: true });
    await expect(name).toBeFocused();
    await name.fill('Reviewed release');
    if (scale === 2) await enlargeComputedText(page);
    await expectDocumentContained(page);
    await expectMainContained(page);
    await page.screenshot({
      path: info.outputPath(`epic-manager-rename-${scale}x.png`),
      fullPage: true,
    });
    await page.getByRole('button', { name: 'Save Epic', exact: true }).click();
    await expect(name).toHaveCount(0);
    expect(renames).toEqual([
      { title: 'Reviewed release', expected_revision: 3 },
    ]);
    const remove = page.getByRole('button', {
      name: 'Delete Epic Reviewed release',
      exact: true,
    });
    page.once('dialog', (dialog) => dialog.accept());
    await remove.click();
    await expect(page.getByRole('alert')).toContainText(
      'Epic membership changed',
    );
    await expect(remove).toBeEnabled();
    expect(deletes).toEqual([{ expected_revision: 4, cohort: 'cohort-10' }]);
    fixtureAPI.mock(
      'DELETE',
      '/api/action-items/epics/10',
      ({ request }: APIRequest) => {
        deletes.push(request.postDataJSON());
        epics = epics.filter((entry) => entry.id !== 10);
        return { deleted: true, id: 10 };
      },
    );
    page.once('dialog', (dialog) => dialog.accept());
    await remove.click();
    await expect(remove).toHaveCount(0);
    expect(deletes).toEqual([
      { expected_revision: 4, cohort: 'cohort-10' },
      { expected_revision: 5, cohort: 'cohort-hidden-completed-change' },
    ]);
    await expect(page.getByText('Release', { exact: true })).toBeVisible();
    expect(
      fixtureAPI.requests.filter(
        (entry) => new URL(entry.url).pathname === '/api/action-items/queue',
      ),
    ).toEqual([]);
  });
}
