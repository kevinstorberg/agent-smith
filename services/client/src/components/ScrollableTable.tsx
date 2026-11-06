import type { ReactNode } from 'react';
import './scrollableTable.css';

export function ScrollableTable({
  label,
  tableLabel,
  className = '',
  empty = false,
  busy,
  emptyState,
  children,
}: {
  label: string;
  tableLabel?: string;
  className?: string;
  empty?: boolean;
  busy?: boolean;
  emptyState?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      className="scrollable-table"
      role="region"
      aria-label={label}
      tabIndex={0}
    >
      <table
        className={`table ${className}${empty ? ' table-empty' : ''}`}
        aria-label={tableLabel}
        aria-busy={busy}
      >
        {children}
      </table>
      {emptyState != null && (
        <div className="scrollable-table-empty-state">{emptyState}</div>
      )}
    </div>
  );
}
