import { test, expect, type APIRequest } from './fixtures';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import {
  expectDocumentContained,
  expectMainContained,
  expectControlReachable,
} from './geometry';
import { enlargeComputedText } from './typography';

test.use({ timezoneId: 'America/New_York', locale: 'en-US' });
test.beforeEach(async ({ fixtureAPI }) => {
  fixtureAPI.get('/api/action-items/projects', {
    items: [{ id: 1, name: 'Work', created_at: '2026-11-01T00:00:00Z' }],
    total: 1,
  });
});

for (const sample of [
  {
    name: 'winter',
    input: '2026-12-01T09:15',
    expected: '2026-12-01T14:15:00.000Z',
    local: 'December 1, 2026 at 09:15 AM',
  },
  {
    name: 'summer midnight crossing',
    input: '2026-07-01T23:15',
    expected: '2026-07-02T03:15:00.000Z',
    local: 'July 1, 2026 at 11:15 PM',
  },
]) {
  test(`local ${sample.name} deadline sends UTC and displays browser-local date/time`, async ({
    page,
    fixtureAPI,
  }) => {
    let saved = actionItem(1);
    fixtureAPI.mock('POST', '/api/action-items', ({ request }: APIRequest) => {
      const body = request.postDataJSON();
      expect(body.due_at).toBe(sample.expected);
      expect(body.project).toBe('Work');
      expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
      saved = actionItem(1, {
        ...body,
        due_at: sample.expected.replace('.000Z', '+00:00'),
      });
      return saved;
    });
    fixtureAPI.get('/api/action-items/1', () => saved);
    await page.goto('/action-items/new?project=Work');
    await page.getByLabel('Title', { exact: true }).fill('Timed task');
    await page.getByLabel('Due date and time').fill(sample.input);
    await expect(
      page.getByText('Times use your local time zone (America/New_York).'),
    ).toBeVisible();
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: 'Timed task', exact: true }),
    ).toBeVisible();
    await expect(page.getByText(sample.local, { exact: true })).toBeVisible();
    await expectDocumentContained(page);
    await expectMainContained(page);
  });
}

test('nonexistent spring-forward local times remain visible without a write', async ({
  page,
  fixtureAPI,
}) => {
  await page.goto('/action-items/new');
  await page.getByLabel('Title', { exact: true }).fill('Do not shift my time');
  await page.getByLabel('Due date and time').fill('2027-03-14T02:30');
  await expect(page.getByRole('alert')).toContainText(
    'This time may not exist',
  );
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  expect(
    fixtureAPI.requests.filter((request) => request.method === 'POST'),
  ).toHaveLength(0);
  await expect(page.getByLabel('Due date and time')).toHaveValue(
    '2027-03-14T02:30',
  );
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(
    'Do not shift my time',
  );
});

test('repeated fall-back hour shows its selected earlier offset before saving', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.mock('POST', '/api/action-items', ({ request }: APIRequest) => {
    expect(request.postDataJSON().due_at).toBe('2026-11-01T05:30:00.000Z');
    return actionItem(1, request.postDataJSON());
  });
  fixtureAPI.get(
    '/api/action-items/1',
    actionItem(1, { due_at: '2026-11-01T05:30:00Z' }),
  );
  await page.goto('/action-items/new');
  await page.getByLabel('Title', { exact: true }).fill('Repeated hour');
  await page.getByLabel('Due date and time').fill('2026-11-01T01:30');
  await expect(page.getByRole('status')).toContainText('GMT-4');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Edit', exact: true }),
  ).toBeVisible();
});

for (const [name, original] of [
  ['microseconds', '2026-07-01T13:15:30.123456+00:00'],
  ['later repeated-hour occurrence', '2026-11-01T06:30:00+00:00'],
]) {
  test(`unrelated edits preserve ${name} and an explicit clear removes the saved deadline`, async ({
    page,
    fixtureAPI,
  }) => {
    let saved = actionItem(1, { due_at: original });
    let writes = 0;
    fixtureAPI.get('/api/action-items/1', () => saved);
    fixtureAPI.mock(
      'PATCH',
      '/api/action-items/1',
      ({ request }: APIRequest) => {
        const body = request.postDataJSON();
        expect(body.expected_revision).toBe(saved.revision);
        expect(body.due_at).toBe(writes === 0 ? original : null);
        writes += 1;
        saved = { ...saved, ...body, revision: saved.revision + 1 };
        return saved;
      },
    );
    await page.goto('/action-items/1?edit=1');
    if (name === 'later repeated-hour occurrence')
      await expect(
        page.getByRole('status').filter({ hasText: 'Selected deadline:' }),
      ).toContainText('GMT-5');
    await page.getByLabel('Title', { exact: true }).fill('Title only');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(
      page.getByRole('button', { name: 'Edit', exact: true }),
    ).toBeVisible();
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await page
      .getByRole('button', { name: 'Clear deadline', exact: true })
      .click();
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(
      page.getByRole('button', { name: 'Edit', exact: true }),
    ).toBeVisible();
    expect(saved.due_at).toBeNull();
    expect(writes).toBe(2);
  });
}

test('hours window stays independent and filtered keyboard drag retains visible anchors', async ({
  page,
  fixtureAPI,
}) => {
  let rows = [
    actionItem(1, { due_at: '2026-11-05T15:00:00Z', priority: 3 }),
    actionItem(2, { due_at: '2026-11-06T15:00:00Z', priority: 7 }),
  ];
  fixtureAPI.get('/api/action-items', ({ url }: APIRequest) => {
    expect(url.searchParams.get('project')).toBe('Work');
    expect(url.searchParams.get('tags')).toBe('security');
    return { items: rows, total: rows.length };
  });
  fixtureAPI.mock(
    'POST',
    '/api/action-items/1/move',
    ({ request }: APIRequest) => {
      expect(request.postDataJSON()).toEqual({
        expected_revision: 1,
        after_id: 2,
      });
      rows = [
        actionItem(2, { due_at: rows[1].due_at, priority: 6 }),
        actionItem(1, { due_at: rows[0].due_at, priority: 7, revision: 2 }),
      ];
      return rows[1];
    },
  );
  await page.goto(
    '/action-items?project=Work&tags=security&due_within_hours=24',
  );
  const slider = page.getByRole('slider', { name: 'Upcoming hours' });
  await expect(slider).toHaveValue('24');
  for (const hours of [5, 48]) {
    await page
      .getByRole('spinbutton', { name: 'Hours', exact: true })
      .fill(String(hours));
    await expect(slider).toHaveValue(String(hours));
    await expect
      .poll(() =>
        fixtureAPI.requests.some(
          (entry) =>
            new URL(entry.url).searchParams.get('due_within_hours') ===
            String(hours),
        ),
      )
      .toBe(true);
  }
  await page.reload();
  await expect(slider).toHaveValue('48');
  await page
    .getByRole('button', { name: 'Reorder Task 1', exact: true })
    .focus();
  await page.keyboard.press('Space');
  await expect(slider).toBeDisabled();
  await expect(
    page.getByRole('checkbox', { name: 'Deadline window' }),
  ).toBeDisabled();
  await expect(
    page.getByRole('spinbutton', { name: 'Hours', exact: true }),
  ).toBeDisabled();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Space');
  await expect(page.getByLabel('Priority 6', { exact: true })).toBeVisible();
  await expect(
    page.getByRole('checkbox', { name: 'Deadline window' }),
  ).toBeEnabled();
  await expect(
    page.getByRole('tab', { name: 'Work', exact: true }),
  ).toHaveAttribute('aria-selected', 'true');
  expect(
    fixtureAPI.requests.filter((request) => request.method === 'POST'),
  ).toHaveLength(1);
});

for (const scale of [1, 2]) {
  test(`deadline controls align with filters and remain reachable at ${scale}x text`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    fixtureAPI.get('/api/action-items', { items: [], total: 0 });
    await page.goto('/action-items?due_within_hours=24');
    if (scale === 2) await enlargeComputedText(page);
    const checkbox = page.getByRole('checkbox', { name: 'Deadline window' });
    const label = checkbox.locator('..');
    const sort = page.getByRole('combobox', { name: 'Sort', exact: true });
    expect
      .soft(
        await checkbox.evaluate((element) =>
          Boolean(element.closest('.profile-filters')),
        ),
      )
      .toBe(true);
    if (scale === 1) {
      const style = await checkbox.evaluate((element) => {
        const input = getComputedStyle(element);
        return {
          appearance: input.appearance,
          width: input.width,
          height: input.height,
          gap: getComputedStyle(element.parentElement!).gap,
        };
      });
      expect.soft(style).toEqual({
        appearance: 'none',
        width: '18px',
        height: '18px',
        gap: '8px',
      });
    }
    expect(
      await checkbox.evaluate((element) => {
        const sort = element
          .closest('.profile-filters')
          ?.querySelector('select');
        return Boolean(
          sort &&
          sort.compareDocumentPosition(element) &
            Node.DOCUMENT_POSITION_FOLLOWING,
        );
      }),
    ).toBe(true);
    const details = page.getByRole('region', { name: 'Deadline filter' });
    await expect(details).toHaveAttribute(
      'id',
      (await checkbox.getAttribute('aria-controls'))!,
    );
    await expect(details).toHaveCSS('grid-column-start', '1');
    await expect(details).toHaveCSS('grid-column-end', '-1');
    if (page.viewportSize()!.width >= 1024) {
      const [sortBox, labelBox] = await Promise.all([
        sort.boundingBox(),
        label.boundingBox(),
      ]);
      expect(
        Math.abs(sortBox!.y + sortBox!.height - labelBox!.y - labelBox!.height),
      ).toBeLessThanOrEqual(2);
      const detailBox = (await details.boundingBox())!;
      expect(detailBox.y).toBeGreaterThanOrEqual(
        labelBox!.y + labelBox!.height,
      );
    }
    await expectControlReachable(checkbox);
    for (const control of await page
      .getByRole('region', { name: 'Deadline filter' })
      .locator('input')
      .all())
      await expectControlReachable(control);
    const hours = page.getByRole('spinbutton', { name: 'Hours', exact: true });
    await hours.fill('169');
    await hours.blur();
    await expect(details.getByRole('alert')).toContainText(
      'current window remains 24 hours',
    );
    await expect(hours).toHaveValue('24');
    await sort.focus();
    await page.keyboard.press('Tab');
    await expect(checkbox).toBeFocused();
    await page.keyboard.press('Space');
    await expect(checkbox).not.toBeChecked();
    await expect(details).toBeHidden();
    await expect(checkbox).toHaveCSS('outline-style', 'solid');
    await page.keyboard.press('Space');
    await expect(checkbox).toBeChecked();
    await expect(details).toBeVisible();
    await expect(details.getByRole('alert')).toHaveCount(0);
    await page.emulateMedia({ forcedColors: 'active' });
    await expect(checkbox).toHaveCSS('appearance', 'auto');
    await expectControlReachable(checkbox);
    await page.emulateMedia({ forcedColors: 'none' });
    await expectDocumentContained(page);
    await expectMainContained(page);
    await testInfo.attach(`deadline-filter-${scale}x.png`, {
      body: await page.screenshot({ fullPage: true }),
      contentType: 'image/png',
    });
    await page.goto('/action-items/new');
    if (scale === 2) await enlargeComputedText(page);
    await page.getByLabel('Due date and time').fill('2026-12-01T09:15');
    await expectControlReachable(page.getByLabel('Due date and time'));
    await expectControlReachable(
      page.getByRole('button', { name: 'Clear deadline' }),
    );
    await expectDocumentContained(page);
    await expectMainContained(page);
  });
}
