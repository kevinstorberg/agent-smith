import type { ReactNode } from 'react';
import { columnDirection, nextColumnSort } from '../../utils/tableSorting';
import type { SortColumn } from '../../utils/tableSorting';
import './sortableHeader.css';

export interface SortButtonProps<T extends string> {
  sort: T;
  column: SortColumn<T>;
  onSort: (sort: T) => void;
  current?: boolean;
  disabled?: boolean;
  title?: string;
  ariaLabel?: string;
  children: ReactNode;
}

export function SortButton<T extends string>({
  sort,
  column,
  onSort,
  current = true,
  disabled = false,
  title,
  ariaLabel,
  children,
}: SortButtonProps<T>) {
  const direction = current ? columnDirection(sort, column) : undefined;
  return (
    <button
      type="button"
      className="sortable-header-button"
      disabled={disabled}
      title={title}
      aria-label={ariaLabel}
      onClick={() => onSort(nextColumnSort(sort, column))}
    >
      <span className="sortable-header-label">{children}</span>
      <span className="sortable-header-icon" aria-hidden="true">
        {direction === 'ascending'
          ? '▲'
          : direction === 'descending'
            ? '▼'
            : '↕'}
      </span>
    </button>
  );
}

export interface SortableHeaderProps<
  T extends string,
> extends SortButtonProps<T> {
  as?: 'th' | 'div';
  className?: string;
}

export function SortableHeader<T extends string>({
  as = 'th',
  className,
  ...props
}: SortableHeaderProps<T>) {
  const direction =
    props.current === false
      ? undefined
      : columnDirection(props.sort, props.column);
  return as === 'div' ? (
    <div role="columnheader" className={className} aria-sort={direction}>
      <SortButton {...props} />
    </div>
  ) : (
    <th scope="col" className={className} aria-sort={direction}>
      <SortButton {...props} />
    </th>
  );
}
