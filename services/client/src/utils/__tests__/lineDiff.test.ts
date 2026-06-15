import { describe, it, expect } from 'vitest';
import { lineDiff } from '../lineDiff';

describe('lineDiff', () => {
  it('marks every line as context when inputs are identical', () => {
    const rows = lineDiff('one\ntwo\nthree', 'one\ntwo\nthree');
    expect(rows.every(r => r.type === 'context')).toBe(true);
    expect(rows.map(r => r.text)).toEqual(['one', 'two', 'three']);
  });

  it('marks a pure insertion as add rows around shared context', () => {
    const rows = lineDiff('one\nthree', 'one\ntwo\nthree');
    expect(rows).toEqual([
      { type: 'context', text: 'one' },
      { type: 'add', text: 'two' },
      { type: 'context', text: 'three' },
    ]);
  });

  it('marks a pure deletion as a remove row', () => {
    const rows = lineDiff('one\ntwo\nthree', 'one\nthree');
    expect(rows).toEqual([
      { type: 'context', text: 'one' },
      { type: 'remove', text: 'two' },
      { type: 'context', text: 'three' },
    ]);
  });

  it('shows a replacement as remove followed by add', () => {
    const rows = lineDiff('## DRY rule', '## DRY rule, clarified');
    expect(rows).toEqual([
      { type: 'remove', text: '## DRY rule' },
      { type: 'add', text: '## DRY rule, clarified' },
    ]);
  });

  it('treats CRLF and LF line endings as equal (no spurious changes)', () => {
    const rows = lineDiff('alpha\r\nbeta', 'alpha\nbeta');
    expect(rows.every(r => r.type === 'context')).toBe(true);
  });
});
