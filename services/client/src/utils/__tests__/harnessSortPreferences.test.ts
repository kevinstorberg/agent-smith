import { describe, expect, it } from 'vitest';
import {
  defaultView,
  harnessViewKey,
  mergeViewCookie,
  parseViewField,
  resolveView,
  viewPath,
} from '../viewPreferences';

const kinds = ['rule', 'skill', 'tool', 'hook', 'agent'] as const;
const commonSorts = [
  'manual',
  'manual_desc',
  'name',
  'name_desc',
  'project_asc',
  'project_desc',
  'enabled_asc',
  'enabled_desc',
  'agents_asc',
  'agents_desc',
  'config_count_asc',
  'config_count_desc',
  'version_asc',
  'version_desc',
  'updated_asc',
  'updated',
  'newest',
];

describe('Harness header sort preference boundaries', () => {
  it.each(kinds)(
    'roundtrips every %s header direction through URL and cookie',
    (kind) => {
      const key = harnessViewKey(kind);
      const sorts =
        kind === 'rule'
          ? [...commonSorts, 'clone_as_skill_asc', 'clone_as_skill_desc']
          : commonSorts;
      for (const sort of sorts) {
        const restored = resolveView(
          key,
          '',
          new URLSearchParams({
            sort,
            name: 'target',
            project: 'scope',
            limit: '25',
            offset: '25',
          }),
        );
        expect(restored.sort).toBe(sort);
        expect(
          resolveView(
            key,
            mergeViewCookie('', key, restored),
            new URLSearchParams(),
          ),
        ).toEqual(restored);
        expect(restored).toMatchObject({
          name: 'target',
          project: 'scope',
          limit: 25,
          offset: 25,
        });
      }
      expect(defaultView(key).sort).toBe('manual');
      expect(viewPath(key)).toBe(
        `/harness/${kind === 'agent' ? 'agents' : `${kind}s`}`,
      );
    },
  );

  it.each(kinds.filter((kind) => kind !== 'rule'))(
    'rejects rule-only clone keys for %s before its first API request',
    (kind) => {
      const key = harnessViewKey(kind);
      for (const sort of ['clone_as_skill_asc', 'clone_as_skill_desc']) {
        expect(parseViewField(key, 'sort', sort)).toBe('manual');
        const cookie = `agent-smith.ui.v1=${encodeURIComponent(
          JSON.stringify({
            v: 1,
            views: [{ key, values: { sort } }],
          }),
        )}`;
        expect(resolveView(key, cookie, new URLSearchParams()).sort).toBe(
          'manual',
        );
      }
    },
  );

  it.each(kinds)('rejects unknown %s sorting tokens', (kind) => {
    expect(
      parseViewField(
        harnessViewKey(kind),
        'sort',
        'name;DROP TABLE harness_rules',
      ),
    ).toBe('manual');
  });
});
