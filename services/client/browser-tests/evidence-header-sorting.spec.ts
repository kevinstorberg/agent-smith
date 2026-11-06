import { test, expect, type APIRequest } from './fixtures';
import { profileFixture } from '../src/pages/__tests__/profileFixture';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';
const path = `/api/profiles/${profileFixture.id}`;
const claim = {
  ...profileFixture.claims[0],
  meeting_title: 'Release review',
  meeting_date: '2026-01-01T12:00:00Z',
};
const result = {
  profile_id: profileFixture.id,
  revision: 1,
  items: [claim],
  total: 45,
};
test.beforeEach(async ({ fixtureAPI }) => {
  fixtureAPI.get(path, profileFixture);
  fixtureAPI.get(`${path}/claims`, result);
});
test('Evidence headers retain criteria, page globally, and preserve corrected display labels', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get(`${path}/claims`, ({ url }: APIRequest) => ({
    ...result,
    items: [
      {
        ...claim,
        status: 'corrected',
        correction: {
          action: 'correct',
          content:
            url.searchParams.get('sort') === 'newest'
              ? 'Human corrected observation'
              : url.searchParams.get('sort') || 'Human corrected observation',
          reason: 'Clarification',
        },
      },
    ],
  }));
  await page.goto(
    `/profiles/${profileFixture.id}?tab=evidence&category=perception&keep=1`,
  );
  const region = page.getByRole('region', {
    name: 'Observation list',
    exact: true,
  });
  await expect(
    region.getByText('Human corrected observation', { exact: true }),
  ).toBeVisible();
  await expect(
    region.getByRole('cell', { name: /^Perceptions/ }),
  ).toBeVisible();
  await expect(region.getByText('Hypothesis', { exact: true })).toBeVisible();
  await expect(
    region.getByText('Corrected by you', { exact: true }),
  ).toBeVisible();
  const section = page.getByRole('region', {
    name: 'Evidence and observations',
    exact: true,
  });
  await section.getByRole('button', { name: 'Next', exact: true }).click();
  for (const [label, key] of [
    ['Observation', 'observation'],
    ['Type', 'type'],
    ['Confidence', 'confidence'],
    ['Review status', 'review'],
    ['Source', 'source'],
  ]) {
    const header = region.getByRole('columnheader', {
      name: label,
      exact: true,
    });
    for (const direction of ['asc', 'desc']) {
      await header.getByRole('button').click();
      await expect(
        region.getByText(`${key}_${direction}`, { exact: true }),
      ).toBeVisible();
      await expect(header).toHaveAttribute(
        'aria-sort',
        direction === 'asc' ? 'ascending' : 'descending',
      );
      const query = new URL(
        fixtureAPI.requests
          .filter((r) => new URL(r.url).pathname === `${path}/claims`)
          .at(-1)!.url,
      ).searchParams;
      expect(Object.fromEntries(query)).toMatchObject({
        category: 'perception',
        offset: '0',
        limit: '20',
        sort: `${key}_${direction}`,
      });
      expect(new URL(page.url()).searchParams.get('keep')).toBe('1');
    }
  }
  expect(fixtureAPI.requests.filter((r) => r.method !== 'GET')).toEqual([]);
});
for (const font of ['computed', 'Arial'])
  test(`Evidence headers remain readable with ${font} at normal and doubled text`, async ({
    page,
  }, info) => {
    await page.goto(`/profiles/${profileFixture.id}?tab=evidence`);
    const region = page.getByRole('region', {
      name: 'Observation list',
      exact: true,
    });
    await expect(
      region.getByText(claim.content, { exact: true }),
    ).toBeVisible();
    if (font === 'Arial')
      await page.addStyleTag({
        content: '* {font-family: Arial, sans-serif !important;}',
      });
    await expectSortableHeaderLayout(page, info, {
      table: region.getByRole('table'),
      scrollRegion: region,
      labels: ['Observation', 'Type', 'Confidence', 'Review status', 'Source'],
      artifactPrefix: `evidence-${font.toLowerCase()}`,
    });
  });
