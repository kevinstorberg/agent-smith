import type { ReactNode } from 'react';

export function ScrollableTable({ label, className = '', empty = false, children }: {
  label: string;
  className?: string;
  empty?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="scrollable-table" role="region" aria-label={label} tabIndex={0}>
      <table className={`table ${className}${empty ? ' table-empty' : ''}`}>{children}</table>
    </div>
  );
}
