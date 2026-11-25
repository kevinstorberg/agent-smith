import type { ActionItemSort } from '../api';
import { ACTION_ITEM_SORT_COLUMNS, actionItemSortOptions } from '../constants';
import { columnDirection } from '../utils/tableSorting';
import type { SortColumn } from '../utils/tableSorting';
import { SortableHeader, SortButton } from './table/SortableHeader';

const SORT_LABELS: Record<ActionItemSort, string> = {
  manual: 'Priority: first to last',
  manual_desc: 'Priority: last to first',
  title: 'Title: A–Z',
  title_desc: 'Title: Z–A',
  project_asc: 'Project: A–Z',
  project_desc: 'Project: Z–A',
  tags_asc: 'Tags: A–Z',
  tags_desc: 'Tags: Z–A',
  due_asc: 'Due: earliest first',
  due_desc: 'Due: latest first',
  updated: 'Updated: newest',
  updated_asc: 'Updated: oldest',
  completed: 'Completed: newest',
  newest: 'Created: newest',
};

export function ActionItemQueueSort({
  sort,
  onSort,
  disabled,
  status,
  orderLabel = 'Priority',
}: {
  sort: ActionItemSort;
  onSort: (sort: ActionItemSort) => void;
  disabled: boolean;
  status: string;
  orderLabel?: string;
}) {
  const options = actionItemSortOptions(
    status === 'open' || status === 'completed' ? status : 'all',
  );
  return (
    <label className="action-item-sort-control">
      <span className="form-label">Sort by</span>
      <select
        className="input"
        value={sort}
        disabled={disabled}
        onChange={(event) => {
          const option = options.find(
            (entry) => entry.value === event.target.value,
          );
          if (option) onSort(option.value);
        }}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.value === 'manual'
              ? `${orderLabel}: first to last`
              : option.value === 'manual_desc'
                ? `${orderLabel}: last to first`
                : SORT_LABELS[option.value]}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ActionItemQueueHead({
  sort,
  onSort,
  current,
  disabled,
  status,
  showProject = true,
  showDueDate = false,
  showUpdated = !showDueDate,
  staticLabels = false,
  taskView = false,
  orderLabel = 'Priority',
}: {
  sort: ActionItemSort;
  onSort: (sort: ActionItemSort) => void;
  current: boolean;
  disabled: boolean;
  status: string;
  showProject?: boolean;
  showDueDate?: boolean;
  showUpdated?: boolean;
  staticLabels?: boolean;
  taskView?: boolean;
  orderLabel?: string;
}) {
  const sorting = { sort, onSort, current, disabled };
  const columns = ACTION_ITEM_SORT_COLUMNS;
  const heading = (
    label: string,
    column: SortColumn<ActionItemSort>,
    title?: string,
    className?: string,
  ) =>
    staticLabels ? (
      <th scope="col" className={className}>
        {label}
      </th>
    ) : (
      <SortableHeader
        {...sorting}
        column={column}
        title={title}
        className={className}
      >
        {label}
      </SortableHeader>
    );
  return (
    <thead className={staticLabels ? 'visually-hidden' : undefined}>
      <tr>
        {status === 'open' ? (
          heading(
            orderLabel,
            columns.priority,
            taskView
              ? `Order by global task ${orderLabel.toLowerCase()}`
              : `Ascending ${orderLabel} enables drag ordering`,
            'action-priority-heading',
          )
        ) : (
          <th scope="col" className="action-priority-heading">
            {orderLabel}
          </th>
        )}
        {heading('Title', columns.title, undefined, 'action-title-heading')}
        {showProject ? (
          staticLabels ? (
            <th scope="col">Project / Tags</th>
          ) : (
            <th
              scope="col"
              aria-sort={
                current
                  ? (columnDirection(sort, columns.project) ??
                    columnDirection(sort, columns.tags))
                  : undefined
              }
            >
              <div className="action-project-tag-sorts">
                <SortButton {...sorting} column={columns.project}>
                  Project
                </SortButton>
                <span aria-hidden="true">/</span>
                <SortButton {...sorting} column={columns.tags}>
                  Tags
                </SortButton>
              </div>
            </th>
          )
        ) : (
          heading('Tags', columns.tags)
        )}
        {showDueDate && heading('Due date', columns.due)}
        {showUpdated && heading('Updated', columns.updated)}
        <th scope="col">Actions</th>
      </tr>
    </thead>
  );
}
