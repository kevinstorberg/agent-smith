import { test, expect } from './fixtures';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';
import { expectControlContained, expectDocumentContained } from './geometry';
import { enlargeComputedText } from './typography';
import { meetingFixture } from '../src/pages/__tests__/meetingFixture';
import { profileFixture } from '../src/pages/__tests__/profileFixture';
import type { MeetingProfiles } from '../src/api';

const rows = [
  {
    ...profileFixture,
    id: 'profile-3',
    display_name: 'Zulu',
    email: 'b@example.test',
  },
  { ...profileFixture, id: 'profile-2', display_name: 'alpha', email: null },
  {
    ...profileFixture,
    id: 'profile-1',
    display_name: 'ALPHA',
    email: 'a@example.test',
  },
];
const path = `/api/meetings/${meetingFixture.id}`;
function register(
  get: (path: string, response: unknown) => void,
  items: MeetingProfiles['items'],
) {
  get(path, meetingFixture);
  const done = { status: 'done', reason: null, error_type: null };
  get(`${path}/processing`, {
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
  });
  get(`${path}/profiles`, { ...done, items });
}

test('Linked profiles sort their full snapshot locally with native keyboard controls and no extra API calls', async ({
  page,
  fixtureAPI,
}) => {
  register(fixtureAPI.get, rows);
  await page.goto(`/meetings/${meetingFixture.id}?tab=profiles`);
  const table = page.getByRole('table', {
    name: 'Linked participant profiles',
  });
  await expect(table.getByRole('row')).toHaveCount(4);
  const names = () =>
    table
      .locator('tbody tr')
      .evaluateAll((rows) =>
        rows.map((row) => row.querySelector('td')!.textContent),
      );
  await expect.poll(names).toEqual(['Zulu', 'alpha', 'ALPHA']);
  const reads = fixtureAPI.requests.filter((entry) =>
    new URL(entry.url).pathname.startsWith('/api/'),
  ).length;
  const name = table.getByRole('button', { name: 'Name', exact: true });
  await name.focus();
  await name.press('Enter');
  await expect.poll(names).toEqual(['ALPHA', 'alpha', 'Zulu']);
  await expect(name).toBeFocused();
  await name.press('Space');
  await expect.poll(names).toEqual(['Zulu', 'ALPHA', 'alpha']);
  await expect(
    table.getByRole('columnheader', { name: 'Name' }),
  ).toHaveAttribute('aria-sort', 'descending');
  const email = table.getByRole('button', { name: 'Email', exact: true });
  await email.click();
  await expect.poll(names).toEqual(['ALPHA', 'Zulu', 'alpha']);
  await email.click();
  await expect.poll(names).toEqual(['Zulu', 'ALPHA', 'alpha']);
  await expect(
    table.getByRole('columnheader', { name: 'Email' }),
  ).toHaveAttribute('aria-sort', 'descending');
  await expect(
    table.getByRole('columnheader', { name: 'Actions' }).getByRole('button'),
  ).toHaveCount(0);
  expect(
    fixtureAPI.requests.filter((entry) =>
      new URL(entry.url).pathname.startsWith('/api/'),
    ),
  ).toHaveLength(reads);
  expect(fixtureAPI.requests.filter((entry) => entry.method !== 'GET')).toEqual(
    [],
  );
});

for (const font of ['default', 'Arial']) {
  test(`Linked profile headers remain readable with actual 1x and 2x ${font} text`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    register(fixtureAPI.get, rows);
    await page.goto(`/meetings/${meetingFixture.id}?tab=profiles`);
    const table = page.getByRole('table', {
      name: 'Linked participant profiles',
    });
    await expect(table.getByRole('row')).toHaveCount(4);
    if (font === 'Arial')
      await page.addStyleTag({
        content: '* {font-family: Arial, sans-serif !important;}',
      });
    await expectSortableHeaderLayout(page, testInfo, {
      table,
      scrollRegion: page.getByRole('region', {
        name: 'Linked profiles list',
        exact: true,
      }),
      labels: ['Name', 'Email'],
      fullyVisibleHeaders: ['Name', 'Email'],
      artifactPrefix: `linked-profiles-${font.toLowerCase()}`,
    });
    const link = table.getByRole('link', { name: "View Zulu's profile" });
    await link.scrollIntoViewIfNeeded();
    await expectControlContained(
      link,
      page.getByRole('region', { name: 'Linked profiles list', exact: true }),
    );
  });
}

test('Empty linked profiles retain sortable headers and contained feedback at doubled text', async ({
  page,
  fixtureAPI,
}) => {
  register(fixtureAPI.get, []);
  await page.goto(`/meetings/${meetingFixture.id}?tab=profiles`);
  const region = page.getByRole('region', {
    name: 'Linked profiles list',
    exact: true,
  });
  const empty = region.getByText(
    'No profiles are linked to this meeting yet. Use Manage participants to connect an existing profile.',
    { exact: true },
  );
  await expect(empty).toBeVisible();
  await enlargeComputedText(page);
  for (const end of [false, true]) {
    await region.evaluate((node, end) => {
      node.scrollLeft = end ? node.scrollWidth : 0;
    }, end);
    await expectControlContained(empty, region);
    await expectDocumentContained(page);
  }
  await region.getByRole('button', { name: 'Name', exact: true }).click();
  await expect(
    region.getByRole('columnheader', { name: 'Name' }),
  ).toHaveAttribute('aria-sort', 'ascending');
});
