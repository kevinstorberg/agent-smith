import { test, expect, type APIRequest } from './fixtures';
import type {
  ActionItemProposal,
  ActionItemProposalApproval,
} from '../src/api';
import { actionItemProposal } from '../src/pages/__tests__/actionItemProposalFixture';
import { epicGroup } from '../src/pages/__tests__/actionItemEpicFixture';
import { epicReference } from '../src/utils/actionItemEpics';
import { chooseEpic, expectEpicSelection } from './epicPicker';
import { enlargeComputedText } from './typography';
import { expectContrast } from './contrast';
import {
  expectControlContained,
  expectDocumentContained,
  expectMainContained,
} from './geometry';

const tasks = [
  'Send the release report',
  'Schedule the launch review',
  'Archive the final checklist',
];
function proposals(): ActionItemProposal[] {
  return tasks.map((title, index) =>
    actionItemProposal({
      id: index + 1,
      action: 'create',
      title: `Create: ${title}`,
      target_name: title,
      target_id: null,
      base_version: null,
      before_snapshot: null,
      current_target: null,
      current_parent: null,
      proposed_item: {
        title,
        description:
          'Confirm the reviewed release checklist and share it with the delivery team.',
        project: 'Work',
        tags: ['release'],
        status: 'open',
      },
      review_outcome: null,
    }),
  );
}

for (const view of ['list', 'detail'] as const) {
  for (const scale of [1, 2]) {
    test(`proposal Done confirms one completed acceptance and preserves an uncertain placement retry in ${view} at ${scale}x text`, async ({
      page,
      fixtureAPI,
    }, info) => {
      let rows = proposals();
      const destination = {
        ...epicGroup(10, []).epic,
        title: 'Release delivery',
      };
      let epics = [destination];
      const writes: ActionItemProposalApproval[] = [];
      const expected = {
        complete: true,
        placement: {
          expected_parent: null,
          destination: epicReference(destination),
        },
      };
      fixtureAPI.get('/api/action-items/epics', () => ({ items: epics }));
      fixtureAPI.get('/api/action-item-proposals', ({ url }: APIRequest) => {
        const status = url.searchParams.get('status');
        const items = status
          ? rows.filter((row) => row.status === status)
          : rows;
        return { items, total: items.length };
      });
      fixtureAPI.get('/api/action-item-proposals/1', () => rows[0]);
      fixtureAPI.get('/api/action-item-proposals/counts', () => ({
        pending: rows.filter((row) => row.status === 'pending').length,
        approved: rows.filter((row) => row.status === 'approved').length,
        rejected: 0,
        superseded: 0,
      }));
      fixtureAPI.mock(
        'POST',
        '/api/action-item-proposals/1/approve',
        ({ request }: APIRequest) => {
          const body = request.postDataJSON() as ActionItemProposalApproval;
          writes.push(body);
          expect(body).toEqual(expected);
          return { detail: 'Completion was not confirmed' };
        },
        504,
      );
      await page.goto(
        view === 'list'
          ? '/action-items/proposals'
          : '/action-items/proposals/1',
      );
      const controls = page
        .locator('.action-item-proposal-decision-controls')
        .first();
      const complete = controls.getByRole('button', {
        name: `Complete ${tasks[0]}`,
        exact: true,
      });
      await expect(complete).toBeEnabled();
      if (
        view === 'list' &&
        scale === 1 &&
        page.viewportSize()!.width === 1440
      ) {
        const last = await page
          .getByRole('list', { name: 'Proposed Action Items', exact: true })
          .getByRole('listitem')
          .last()
          .boundingBox();
        expect(
          last!.y + last!.height,
          'Three representative rows retain their compact desktop density with Done',
        ).toBeLessThanOrEqual(900);
      }
      const choice = controls.getByRole('button', { name: /Epic for/ });
      await chooseEpic(choice, '10');
      if (scale === 2) await enlargeComputedText(page);
      for (const button of [
        complete,
        controls.getByRole('button', { name: 'Accept', exact: true }),
        controls.getByRole('button', { name: 'Reject', exact: true }),
      ])
        await expectControlContained(button, controls);
      const [doneBounds, acceptBounds, rejectBounds] = await Promise.all([
        complete.boundingBox(),
        controls
          .getByRole('button', { name: 'Accept', exact: true })
          .boundingBox(),
        controls
          .getByRole('button', { name: 'Reject', exact: true })
          .boundingBox(),
      ]);
      await info.attach('decision-geometry.json', {
        contentType: 'application/json',
        body: JSON.stringify(
          await controls.evaluate((element) => ({
            availableWidth: element.clientWidth,
            gap: getComputedStyle(
              element.querySelector('.action-item-proposal-decision-buttons')!,
            ).gap,
            buttons: Array.from(
              element.querySelectorAll(
                '.action-item-proposal-decision-buttons button',
              ),
            ).map((button) => ({
              label: button.getAttribute('aria-label') || button.textContent,
              width: button.getBoundingClientRect().width,
              height: button.getBoundingClientRect().height,
              fontSize: getComputedStyle(button).fontSize,
              paddingInline: getComputedStyle(button).paddingInline,
            })),
          })),
          null,
          2,
        ),
      });
      expect(Math.abs(acceptBounds!.y - rejectBounds!.y)).toBeLessThanOrEqual(
        1,
      );
      expect(
        Math.abs(
          doneBounds!.y +
            doneBounds!.height / 2 -
            (acceptBounds!.y + acceptBounds!.height / 2),
        ),
      ).toBeLessThanOrEqual(1);
      await expectContrast(complete, 3);
      await complete.hover();
      await complete.evaluate(async (element) => {
        await Promise.allSettled(
          element.getAnimations().map((animation) => animation.finished),
        );
      });
      await expectContrast(complete, 3);
      await expectDocumentContained(page);
      await expectMainContained(page);
      await page.screenshot({
        path: info.outputPath(`proposal-done-${view}-${scale}x.png`),
        fullPage: true,
      });
      page.once('dialog', async (dialog) => {
        expect(dialog.message()).toContain('Accept this proposal');
        expect(dialog.message()).toContain('as completed');
        await dialog.dismiss();
      });
      await complete.click();
      expect(writes).toEqual([]);
      page.once('dialog', (dialog) => dialog.accept());
      await complete.click();
      await expect(
        page
          .getByRole('alert')
          .filter({ hasText: 'Completion was not confirmed' }),
      ).toBeVisible();
      await expect(complete).toBeEnabled();
      expect(writes).toEqual([expected]);
      await expect(
        page.getByText('accepted as done', { exact: true }),
      ).toHaveCount(0);
      epics = [
        {
          ...destination,
          title: 'Changed delivery',
          revision: 9,
          cohort: 'changed-membership',
        },
      ];
      await page
        .getByRole('button', { name: 'Refresh Epics', exact: true })
        .click();
      await expectEpicSelection(choice, 'Release delivery — earlier choice');
      fixtureAPI.mock(
        'POST',
        '/api/action-item-proposals/1/approve',
        ({ request }: APIRequest) => {
          const body = request.postDataJSON() as ActionItemProposalApproval;
          writes.push(body);
          rows = rows.map((row) =>
            row.id === 1
              ? {
                  ...row,
                  status: 'approved',
                  review_outcome: 'completed',
                  applied_ref: {
                    action_item_id: 12,
                    review_outcome: 'completed',
                    placement: body.placement,
                  },
                }
              : row,
          );
          return rows[0];
        },
      );
      page.once('dialog', (dialog) => dialog.accept());
      await complete.focus();
      await page.keyboard.press('Space');
      await expect.poll(() => writes.length).toBe(2);
      expect(writes).toEqual([expected, expected]);
      await expect(complete).toHaveCount(0);
      rows = rows.map((row) =>
        row.id === 1
          ? { ...row, current_target: { status: 'open', revision: 99 } }
          : row,
      );
      await page.goto(
        view === 'list'
          ? '/action-items/proposals?status=approved'
          : '/action-items/proposals/1',
      );
      await expect(
        page.getByText('accepted as done', { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole('button', { name: `Complete ${tasks[0]}`, exact: true }),
      ).toHaveCount(0);
      expect(
        fixtureAPI.requests.filter((request) => request.method !== 'GET'),
      ).toHaveLength(2);
    });
  }

  test(`proposal Done refuses an additional decision when a409 refresh marks the ${view} source stale`, async ({
    page,
    fixtureAPI,
  }) => {
    let proposal = proposals()[0];
    const writes: unknown[] = [];
    fixtureAPI.get('/api/action-items/epics', { items: [] });
    fixtureAPI.get('/api/action-item-proposals', () => ({
      items: [proposal],
      total: 1,
    }));
    fixtureAPI.get('/api/action-item-proposals/1', () => proposal);
    fixtureAPI.get('/api/action-item-proposals/counts', {
      pending: 1,
      approved: 0,
      rejected: 0,
      superseded: 0,
    });
    fixtureAPI.mock(
      'POST',
      '/api/action-item-proposals/1/approve',
      ({ request }: APIRequest) => {
        writes.push(request.postDataJSON());
        proposal = { ...proposal, source_stale: true };
        return { detail: 'Source changed during review' };
      },
      409,
    );
    await page.goto(
      view === 'list' ? '/action-items/proposals' : '/action-items/proposals/1',
    );
    const complete = page.getByRole('button', {
      name: `Complete ${tasks[0]}`,
      exact: true,
    });
    page.once('dialog', (dialog) => dialog.accept());
    await complete.click();
    await expect(
      page
        .getByRole('alert')
        .filter({ hasText: 'Source changed during review' }),
    ).toBeVisible();
    await expect(complete).toBeDisabled();
    await expect(
      page.getByRole('button', { name: 'Accept', exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByRole('button', { name: 'Reject', exact: true }),
    ).toBeEnabled();
    expect(writes).toEqual([{ complete: true }]);
    expect(
      fixtureAPI.requests.filter((request) => request.method !== 'GET'),
    ).toHaveLength(1);
  });
}
