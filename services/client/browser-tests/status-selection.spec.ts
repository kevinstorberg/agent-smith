import type { Locator, Page, TestInfo } from '@playwright/test';
import type {
  MeetingParticipants,
  MeetingProcessingState,
  ProfileRevision,
} from '../src/api';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import { meetingFixture } from '../src/pages/__tests__/meetingFixture';
import { profileFixture } from '../src/pages/__tests__/profileFixture';
import { expectContrast } from './contrast';
import { test, expect, type APIRequest } from './fixtures';
import {
  expectControlContained,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { runFixture } from './operationsFixture';
import { meetingAnalysisCandidatesPage } from './meetingAnalysisFixture';
import { enlargeComputedText } from './typography';

const profilePath = `/api/profiles/${profileFixture.id}`;
const meetingPath = `/api/meetings/${meetingFixture.id}`;
const participants: MeetingParticipants = {
  revision: 1,
  items: [],
  people: [],
  provider_participants: [],
  speakers: [],
  running: false,
  enrolled: false,
};
const progress = {
  processed_units: 0,
  total_units: null,
  staged_count: 0,
  saved_count: 0,
  attempts: 0,
  next_attempt_at: null,
};
const processing: MeetingProcessingState = {
  transcript: {
    status: 'ready',
    total: 0,
    error_type: null,
    captured_at: null,
  },
  speakers: { status: 'not_imported', error_type: null, progress },
  memories: { status: 'done', reason: null, error_type: null, progress },
  profiles: { status: 'done', reason: null, error_type: null, progress },
  edit_lock_reason: null,
};
const revision: ProfileRevision = {
  id: 12,
  profile_id: profileFixture.id,
  base_revision: 1,
  new_revision: 2,
  actor: 'human',
  source: 'assessment',
  source_id: null,
  input_hash: 'browser-fixture',
  created_at: profileFixture.updated_at,
  changes: {
    'section_notes.drivers': {
      before: 'Earlier delivery context.',
      after: 'Current delivery context.',
    },
  },
};

interface SelectionView {
  name: string;
  path: string;
  labels: string[];
  group: (page: Page) => Locator;
  open?: (page: Page) => Promise<void>;
  disabled?: 'queue' | 'evidence' | 'participant';
}

const views: SelectionView[] = [
  {
    name: 'Action items',
    path: '/action-items',
    labels: ['Open', 'Completed', 'All'],
    group: (page) => page.getByRole('tablist', { name: 'Action item status' }),
    disabled: 'queue',
  },
  {
    name: 'Discussion topics',
    path: `/profiles/${profileFixture.id}?tab=topics`,
    labels: ['Open', 'Completed', 'All'],
    group: (page) =>
      page.getByRole('tablist', { name: 'Discussion topic status' }),
    disabled: 'queue',
  },
  {
    name: 'Result chart',
    path: '/evals',
    labels: ['Average', 'Breakdown'],
    group: (page) => page.locator('.sub-tabs'),
  },
  {
    name: 'Result details',
    path: '/evals/1',
    labels: ['Overview', 'Agent Output', 'Raw JSON'],
    group: (page) => page.locator('.sub-tabs'),
  },
  {
    name: 'Meeting candidates',
    path: `/profiles/${profileFixture.id}`,
    labels: ['Related meetings', 'All saved meetings'],
    open: async (page) => {
      await page
        .getByRole('button', { name: 'Review past meetings', exact: true })
        .click();
    },
    group: (page) => page.getByRole('group', { name: 'Meeting candidates' }),
  },
  {
    name: 'Observation kinds',
    path: `/profiles/${profileFixture.id}?tab=evidence`,
    labels: ['All', 'Observed', 'Self-reported', 'Hypotheses'],
    group: (page) => page.getByRole('group', { name: 'Observation kinds' }),
    disabled: 'evidence',
  },
  {
    name: 'Participant source',
    path: `/meetings/${meetingFixture.id}?tab=transcript`,
    labels: ['Existing profile', 'Name and email'],
    open: async (page) => {
      await page
        .getByRole('button', { name: 'Add participant', exact: true })
        .click();
    },
    group: (page) => page.getByRole('group', { name: 'Participant source' }),
    disabled: 'participant',
  },
  {
    name: 'Profile history',
    path: `/profiles/${profileFixture.id}`,
    labels: ['Changes', 'Before', 'After'],
    open: async (page) => {
      await page.getByText('History', { exact: true }).click();
      await page.getByRole('button', { name: 'View change #12' }).click();
    },
    group: (page) =>
      page
        .getByRole('region', { name: 'Profile change 12' })
        .locator('.sub-tabs'),
  },
];

async function capture(group: Locator, info: TestInfo, state: string) {
  await settleSelection(group);
  await group.evaluate((element) =>
    element.scrollIntoView({ block: 'center', inline: 'nearest' }),
  );
  const bounds = (await group.boundingBox())!;
  const viewport = group.page().viewportSize()!;
  const x = Math.max(0, bounds.x - 8);
  const y = Math.max(0, bounds.y - 8);
  const path = info.outputPath(`${state}.png`);
  await group.page().screenshot({
    path,
    clip: {
      x,
      y,
      width: Math.min(viewport.width - x, bounds.width + 16),
      height: Math.min(viewport.height - y, bounds.height + 16),
    },
  });
  await info.attach(state, { path, contentType: 'image/png' });
}

async function expectSelection(group: Locator, label: string) {
  const selected = group.getByRole(
    /tablist/.test((await group.getAttribute('role')) || '') ? 'tab' : 'button',
    { name: label, exact: true },
  );
  await expect(selected).toHaveClass(/active/);
  await expect(selected).toHaveAttribute(
    (await selected.getAttribute('role')) === 'tab'
      ? 'aria-selected'
      : 'aria-pressed',
    'true',
  );
  await expect(group.locator('button.active')).toHaveCount(1);
  return selected;
}

async function expectReadableGroup(group: Locator) {
  await settleSelection(group);
  for (const button of await group.locator('button').all()) {
    await expectControlContained(button, group);
    await expectContrast(button);
    await expectContrast(button, 3, 'borderTopColor');
    const text = await button.evaluate((element) => {
      const range = document.createRange();
      range.selectNodeContents(element);
      const bounds = element.getBoundingClientRect();
      return {
        bounds: {
          left: bounds.left,
          right: bounds.right,
          top: bounds.top,
          bottom: bounds.bottom,
        },
        lines: [...range.getClientRects()].map((line) => ({
          left: line.left,
          right: line.right,
          top: line.top,
          bottom: line.bottom,
        })),
      };
    });
    for (const line of text.lines) {
      expect(line.left).toBeGreaterThanOrEqual(text.bounds.left - 1);
      expect(line.right).toBeLessThanOrEqual(text.bounds.right + 1);
      expect(line.top).toBeGreaterThanOrEqual(text.bounds.top - 1);
      expect(line.bottom).toBeLessThanOrEqual(text.bounds.bottom + 1);
    }
  }
}

async function settleSelection(group: Locator) {
  await group.evaluate(async (element) => {
    await Promise.allSettled(
      element
        .getAnimations({ subtree: true })
        .map((animation) => animation.finished),
    );
  });
}

async function buttonGeometry(group: Locator) {
  return group.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    return [...element.querySelectorAll('button')].map((button) => {
      const rect = button.getBoundingClientRect();
      return [rect.x - bounds.x, rect.y - bounds.y, rect.width, rect.height];
    });
  });
}

async function verifyDisabledSelection(
  group: Locator,
  info: TestInfo,
  release: () => Promise<void>,
) {
  const page = group.page();
  try {
    await expect(group.locator('button:disabled')).toHaveCount(
      await group.locator('button').count(),
    );
    await capture(group, info, 'disabled');
    const inactive = group.locator('button:not(.active)').first();
    const color = await inactive.evaluate(
      (element) => getComputedStyle(element).color,
    );
    await inactive.hover();
    await settleSelection(group);
    await expect(inactive).toHaveCSS('color', color);
    await capture(group, info, 'disabled-hover');
    await page.emulateMedia({ forcedColors: 'active' });
    await capture(group, info, 'disabled-forced-colors');
  } finally {
    await page.emulateMedia({ forcedColors: 'none' });
    await release();
  }
  await expect(group.locator('button:disabled')).toHaveCount(0);
}

for (const view of views) {
  for (const scale of [1, 2]) {
    test(`${view.name} selection remains readable at ${scale}x text`, async ({
      page,
      fixtureAPI,
    }, info) => {
      fixtureAPI.get('/api/action-items', ({ url }: APIRequest) => {
        const status =
          url.searchParams.get('status') === 'completed' ? 'completed' : 'open';
        return {
          items: [actionItem(1, { status }), actionItem(2, { status })],
          total: 2,
        };
      });
      fixtureAPI.get(profilePath, profileFixture);
      fixtureAPI.get(
        `${profilePath}/discussion-topics`,
        ({ url }: APIRequest) => {
          const status =
            url.searchParams.get('status') === 'completed'
              ? 'completed'
              : 'open';
          return {
            profile_id: profileFixture.id,
            items: [1, 2].map((id) => ({
              ...actionItem(id, { status }),
              profile_id: profileFixture.id,
            })),
            total: 2,
          };
        },
      );
      fixtureAPI.get(`${profilePath}/claims`, {
        profile_id: profileFixture.id,
        revision: 1,
        items: profileFixture.claims,
        total: 1,
      });
      fixtureAPI.get(`${profilePath}/history`, { items: [revision], total: 1 });
      fixtureAPI.get(`${profilePath}/history/12`, revision);
      fixtureAPI.get(
        '/api/meeting-analysis/candidates',
        ({ url }: APIRequest) => meetingAnalysisCandidatesPage(url, 0),
      );
      fixtureAPI.get(meetingPath, meetingFixture);
      fixtureAPI.get(`${meetingPath}/processing`, processing);
      let participantRead: MeetingParticipants = {
        ...participants,
        running: view.disabled === 'participant',
        edit_lock_reason: null,
      };
      fixtureAPI.get(`${meetingPath}/participants`, () => participantRead);
      fixtureAPI.get(`${meetingPath}/transcript`, {
        status: 'ready',
        items: [],
        total: 0,
        limit: 100,
        offset: 0,
        error_type: null,
        captured_at: null,
      });
      fixtureAPI.get('/api/profiles', { items: [], total: 0 });
      fixtureAPI.get('/api/evals', { items: [runFixture()], total: 1 });
      fixtureAPI.get('/api/evals/1', {
        ...runFixture(),
        prompt: 'Review release context',
        output: 'Ready',
        results: [],
      });
      fixtureAPI.get('/api/evals/categories', ['rules']);
      fixtureAPI.get('/api/evals/subcategories', ['release']);
      fixtureAPI.get('/api/evals/facets', { scenarios: [], models: [] });
      fixtureAPI.get('/api/evals/chart/average', []);
      fixtureAPI.get('/api/evals/chart', []);

      if (view.disabled === 'participant') await page.clock.install();
      await page.goto(view.path);
      await view.open?.(page);
      const group = view.group(page);
      await expect(group.locator('button')).toHaveText(view.labels);
      await expect(
        page.locator('link[rel="stylesheet"][href^="/assets/"]'),
      ).toHaveCount(1);
      if (scale === 2) await enlargeComputedText(page);
      const initialGeometry = await buttonGeometry(group);
      await capture(group, info, 'normal');
      const last = group.locator('button').last();
      await last.hover();
      await capture(group, info, 'hover');
      for (const label of view.labels) {
        await group
          .getByRole(
            view.name === 'Action items' || view.name === 'Discussion topics'
              ? 'tab'
              : 'button',
            { name: label, exact: true },
          )
          .click();
        await expectSelection(group, label);
        const positions = await buttonGeometry(group);
        positions.forEach((position, index) =>
          position.forEach((value, dimension) =>
            expect(
              Math.abs(value - initialGeometry[index][dimension]),
              'Selecting a different view preserves control geometry',
            ).toBeLessThanOrEqual(0.5),
          ),
        );
      }
      await group.locator('button.active').hover();
      await capture(group, info, 'selected-hover');
      await group.locator('button').first().focus();
      await page.keyboard.press('Tab');
      const focused = group.locator('button').nth(1);
      await expect(focused).toBeFocused();
      await page.keyboard.press('Space');
      await expectSelection(group, view.labels[1]);
      await expect(focused).toHaveCSS('outline-style', 'solid');
      await expect(focused).toHaveCSS('outline-width', '2px');
      await capture(group, info, 'focus');
      await page.emulateMedia({ forcedColors: 'active' });
      await capture(group, info, 'forced-colors');
      await expectReadableGroup(group);
      await page.emulateMedia({ forcedColors: 'none' });

      if (view.disabled === 'queue') {
        await group.getByRole('tab', { name: 'Open', exact: true }).click();
        const handle = page.getByRole('button', {
          name: 'Reorder Task 1',
          exact: true,
        });
        await expect(handle).toBeEnabled();
        await handle.focus();
        await page.keyboard.press('Space');
        await verifyDisabledSelection(group, info, () =>
          page.keyboard.press('Escape'),
        );
      } else if (view.disabled === 'evidence') {
        await page
          .getByRole('button', { name: 'View observation', exact: true })
          .click();
        await page
          .getByRole('button', { name: 'Correct claim', exact: true })
          .click();
        await verifyDisabledSelection(group, info, () =>
          page.getByRole('button', { name: 'Cancel', exact: true }).click(),
        );
      } else if (view.disabled === 'participant') {
        participantRead = {
          ...participantRead,
          edit_lock_reason: 'analyzing_personas',
        };
        await page.clock.fastForward(60_000);
        await verifyDisabledSelection(group, info, async () => {
          participantRead = { ...participantRead, edit_lock_reason: null };
          await page.clock.fastForward(60_000);
        });
      }

      await expectReadableGroup(group);
      await expect(group.locator('button.active')).toHaveCSS(
        'box-shadow',
        'none',
      );
      if (scale === 1) {
        await expectDocumentContained(page);
        await expectMainContained(page);
      }
      expect(
        fixtureAPI.requests.filter((request) => request.method !== 'GET'),
      ).toEqual([]);
    });
  }
}

test.beforeEach(async ({ fixtureAPI }) => {
  fixtureAPI.get('/api/action-items/projects', { items: [], total: 0 });
});
