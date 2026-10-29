import { describe, expect, it } from 'vitest';
import { parseTags } from '../tags';

describe('parseTags', () => {
  it('trims empty entries and duplicate tags while preserving case and order', () => {
    expect(parseTags(' team, Priority,team,, Priority ')).toEqual(['team', 'Priority']);
    expect(parseTags(' , ')).toEqual([]);
  });
});
