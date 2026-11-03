import type { HarnessItem } from '../src/api';

export function harnessFixture(overrides: Partial<HarnessItem> = {}): HarnessItem {
  return { id: 1, name: 'release_review', project: 'browser-fixture', agents: ['claude'],
    content: { body: '## Release notes\n\nA clear description of the next steps.', metadata: {} }, sort_key: 1, enabled: true,
    version: 1, created_at: '2026-11-03T12:00:00Z', updated_at: '2026-11-03T12:00:00Z', configs: [], ...overrides };
}
