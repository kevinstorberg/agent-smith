import type { CSSProperties } from 'react';

export const CODE_BOX: CSSProperties = {
  whiteSpace: 'pre-wrap',
  overflowWrap: 'anywhere',
  background: 'var(--surface-elevated)',
  color: 'var(--text)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius)',
  fontFamily: 'var(--mono)',
  fontSize: 12.5,
  lineHeight: 1.6,
  padding: 14,
  margin: 0,
  maxHeight: 520,
  overflow: 'auto',
};
