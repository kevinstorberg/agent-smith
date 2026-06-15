export interface DiffRow {
  type: 'context' | 'add' | 'remove';
  text: string;
}

/** Normalize line endings (CRLF/CR -> LF) so they never register as changes, then split. */
function toLines(source: string): string[] {
  return source.replace(/\r\n?/g, '\n').split('\n');
}

/**
 * Line-level diff via longest-common-subsequence. Returns rows in document order:
 * unchanged lines as 'context', and changed regions as 'remove' lines (from the
 * old text) followed by 'add' lines (from the new text), git unified-diff style.
 */
export function lineDiff(before: string, after: string): DiffRow[] {
  const a = toLines(before);
  const b = toLines(after);
  const n = a.length;
  const m = b.length;

  // lcs[i][j] = length of the LCS of a[i:] and b[j:].
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ type: 'context', text: a[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      rows.push({ type: 'remove', text: a[i] });
      i++;
    } else {
      rows.push({ type: 'add', text: b[j] });
      j++;
    }
  }
  while (i < n) rows.push({ type: 'remove', text: a[i++] });
  while (j < m) rows.push({ type: 'add', text: b[j++] });
  return rows;
}
