import { lineDiff, type DiffRow } from '../utils/lineDiff';
import { CODE_BOX } from './codeBox';

const ROW_STYLE: Record<DiffRow['type'], React.CSSProperties> = {
  context: {},
  add: { background: 'rgba(46, 160, 67, 0.18)' },
  remove: { background: 'rgba(248, 81, 73, 0.18)' },
};
const GUTTER: Record<DiffRow['type'], string> = { context: ' ', add: '+', remove: '-' };

export function ContentDiff({ before, after }: { before: string; after: string }) {
  return <pre style={CODE_BOX}>{lineDiff(before, after).map((row, index) => (
    <div key={index} data-diff={row.type} style={{ display: 'flex', ...ROW_STYLE[row.type] }}>
      <span style={{ width: 16, flexShrink: 0, opacity: 0.5, userSelect: 'none' }}>{GUTTER[row.type]}</span>
      <span style={{ flex: 1, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{row.text || ' '}</span>
    </div>
  ))}</pre>;
}
