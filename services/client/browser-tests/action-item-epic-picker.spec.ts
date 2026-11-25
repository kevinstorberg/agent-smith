import { test, expect, type APIRequest } from './fixtures';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import {
  epicGroup,
  queuePage,
} from '../src/pages/__tests__/actionItemEpicFixture';
import { openItemActions } from './actionItemDisclosures';
import { openEpicPicker } from './epicPicker';
import { enlargeComputedText } from './typography';
import {
  expectControlContained,
  expectControlReachable,
  expectDialogContained,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import type { ActionItemQueueRoot } from '../src/api';

for (const scale of [1, 2]) {
  test(`Epic search chooses explicitly from a long catalog without writes while searching at ${scale}x text`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    const task = actionItem(1);
    const longName =
      'Customer onboarding, clinical integrations, security readiness and partner delivery';
    const destination = { ...epicGroup(99, []).epic, title: longName };
    const epics = [
      ...Array.from({ length: 45 }, (_, i) => ({
        ...epicGroup(i + 10, []).epic,
        title: `Project planning ${i + 1}`,
      })),
      destination,
      { ...epicGroup(100, []).epic, title: longName },
    ];
    let roots: ActionItemQueueRoot[] = queuePage({
      items: [task],
      total: 1,
    }).items;
    const bodies: unknown[] = [];
    fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
    fixtureAPI.get('/api/action-items/queue', () => ({
      items: roots,
      total: roots.length,
      matching_count: 1,
    }));
    fixtureAPI.get('/api/action-items/epics', { items: epics });
    fixtureAPI.mock(
      'POST',
      '/api/action-items/1/epic',
      ({ request }: APIRequest) => {
        bodies.push(request.postDataJSON());
        const group = epicGroup(99, [task]);
        group.epic = destination;
        roots = [group];
        return task;
      },
    );
    await page.goto('/action-items');
    await openItemActions(page, task.title);
    await page
      .getByRole('button', { name: `Move ${task.title} to Epic`, exact: true })
      .click();
    const trigger = page.getByRole('button', {
      name: 'Move to Epic',
      exact: true,
    });
    let popup = await openEpicPicker(trigger);
    await expect(
      popup.getByRole('searchbox', { name: 'Find Epic' }),
    ).toBeFocused();
    await expect(popup.getByRole('status')).toHaveText(
      'Showing 20 of 47 Epics. Refine your search.',
    );
    await expect(popup.locator('.epic-choice-results button')).toHaveCount(20);
    const search = popup.getByRole('searchbox');
    await search.fill('not present');
    await expect(
      popup.getByText('No matching Epics', { exact: true }),
    ).toBeVisible();
    await search.press('Enter');
    expect(bodies).toEqual([]);
    await popup.getByRole('button', { name: 'Clear Epic search' }).click();
    await search.fill('customer');
    const option = popup.getByRole('button', {
      name: `${longName} #99`,
      exact: true,
    });
    await expect(option).toBeVisible();
    await expect(
      popup.getByRole('button', { name: `${longName} #100`, exact: true }),
    ).toBeVisible();
    const baseOptionFont = await option.evaluate((element) =>
      parseFloat(getComputedStyle(element).fontSize),
    );
    const restore =
      scale === 2
        ? await enlargeComputedText(page, 2, { restorable: true })
        : null;
    expect(
      await option.evaluate((element) =>
        parseFloat(getComputedStyle(element).fontSize),
      ),
    ).toBeCloseTo(baseOptionFont * scale, 1);
    await expectDialogContained(popup);
    await expectControlContained(option, popup);
    await expectControlReachable(option);
    await search.focus();
    await search.press('Enter');
    await expect(option).toBeFocused();
    expect(bodies).toEqual([]);
    await restore?.();
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    popup = await openEpicPicker(trigger);
    const freshSearch = popup.getByRole('searchbox');
    await expect(freshSearch).toHaveValue('');
    await freshSearch.fill('customer');
    const baseSearchFont = await freshSearch.evaluate((element) =>
      parseFloat(getComputedStyle(element).fontSize),
    );
    if (scale === 2) await enlargeComputedText(page);
    expect(
      await freshSearch.evaluate((element) =>
        parseFloat(getComputedStyle(element).fontSize),
      ),
    ).toBeCloseTo(baseSearchFont * scale, 1);
    await expectDialogContained(popup);
    await page.screenshot({
      path: testInfo.outputPath(`searchable-epic-${scale}x.png`),
      fullPage: true,
      animations: 'disabled',
    });
    expect(
      fixtureAPI.requests.filter((request) => request.method !== 'GET'),
    ).toEqual([]);
    await freshSearch.press('ArrowDown');
    await page.keyboard.press('Enter');
    await expect.poll(() => bodies.length).toBe(1);
    expect(bodies).toEqual([
      {
        expected_revision: task.revision,
        expected_parent: null,
        destination: {
          id: 99,
          expected_revision: destination.revision,
          cohort: destination.cohort,
        },
      },
    ]);
    await expect(
      page
        .getByRole('region', { name: `Epic ${longName}`, exact: true })
        .getByRole('button', { name: task.title, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole('searchbox', { name: 'Find Epic', exact: true }),
    ).toHaveCount(0);
    await expect(page.locator('#main-content')).toContainText(task.title);
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            document.activeElement !== document.body &&
            Boolean(document.activeElement?.closest('#main-content')),
        ),
      )
      .toBe(true);
    await expectDocumentContained(page);
    await expectMainContained(page);
  });
}
