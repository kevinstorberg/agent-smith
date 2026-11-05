import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  changeDeadline,
  deadlineDraft,
  deadlineFields,
} from '../actionItemDeadlines';

afterEach(() => vi.restoreAllMocks());

describe('deadline draft conversion', () => {
  it('retains exact original precision unless the user changes the local value', () => {
    const original = '2026-07-01T13:15:30.123456+00:00';
    const draft = deadlineDraft(original);
    expect(deadlineFields(draft)).toEqual({ due_at: original });
    const changed = changeDeadline(draft, '2026-12-01T09:15');
    expect(deadlineFields(changed)).toEqual({
      due_at: new Date(2026, 11, 1, 9, 15).toISOString(),
    });
    expect(deadlineFields(changeDeadline(draft, draft.initialLocal))).toEqual({
      due_at: original,
    });
  });
  it('distinguishes an explicit clear from an untouched undated draft', () => {
    expect(deadlineFields(deadlineDraft())).toEqual({});
    expect(
      deadlineFields(changeDeadline(deadlineDraft('2026-07-01T13:15:00Z'), '')),
    ).toEqual({ due_at: null });
  });
  it.each(['2026-02-30T09:15', '2026-01-01', '0000-01-01T09:15', 'not a date'])(
    'rejects invalid local calendar inputs: %s',
    (value) => {
      expect(() =>
        deadlineFields(changeDeadline(deadlineDraft(), value)),
      ).toThrow(/valid local date and time/i);
    },
  );
  it('rejects a changed time zone after capture while keeping untouched original timestamps safe', () => {
    const original = deadlineDraft('2026-07-01T13:15:30.123456+00:00');
    const changed = changeDeadline(original, '2026-12-01T09:15');
    const resolved = Intl.DateTimeFormat.prototype.resolvedOptions;
    vi.spyOn(
      Intl.DateTimeFormat.prototype,
      'resolvedOptions',
    ).mockImplementation(function (this: Intl.DateTimeFormat) {
      return { ...resolved.call(this), timeZone: 'Changed/Zone' };
    });
    expect(() => deadlineFields(changed)).toThrow(/time zone changed/i);
    expect(deadlineFields(original)).toEqual({ due_at: original.original });
  });
});
