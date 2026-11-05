import { describe, expect, it } from 'vitest';
import { defaultView, mergeViewCookie, resolveView } from '../viewPreferences';

describe('deadline window preferences', () => {
  it.each(['0', '169', 'true', '1.5', '-1', ''])(
    'rejects invalid hours without truncation or coercion: %s',
    (value) => {
      expect(
        resolveView(
          'actionItems',
          '',
          new URLSearchParams({ due_within_hours: value }),
        ).due_within_hours,
      ).toBeNull();
    },
  );
  it.each([1, 5, 24, 48, 168])(
    'persists an independent valid hours window: %s',
    (hours) => {
      const cookie = mergeViewCookie('', 'actionItems', {
        ...defaultView('actionItems'),
        due_within_hours: hours,
        unassigned: true,
        status: 'completed',
        tags: 'security',
      });
      expect(
        resolveView('actionItems', cookie, new URLSearchParams()),
      ).toMatchObject({
        due_within_hours: hours,
        unassigned: true,
        project: '',
        status: 'completed',
        tags: 'security',
      });
      expect(
        resolveView(
          'actionItems',
          cookie,
          new URLSearchParams('due_within_hours='),
        ),
      ).toMatchObject({
        due_within_hours: null,
        unassigned: true,
        status: 'completed',
        tags: 'security',
      });
    },
  );
});
