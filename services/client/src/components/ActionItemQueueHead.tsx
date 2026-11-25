import type { ActionItemSort } from '../api';
import { ACTION_ITEM_SORT_COLUMNS } from '../constants';
import { columnDirection } from '../utils/tableSorting';
import type { SortColumn } from '../utils/tableSorting';
import { SortableHeader, SortButton } from './table/SortableHeader';

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
}) {
  const sorting = { sort, onSort, current, disabled };
  const columns = ACTION_ITEM_SORT_COLUMNS;
  const heading = (
    label: string,
    column: SortColumn<ActionItemSort>,
    title?: string,
  ) =>
    staticLabels ? (
      <th scope="col">{label}</th>
    ) : (
      <SortableHeader {...sorting} column={column} title={title}>
        {label}
      </SortableHeader>
    );
  return (
    <thead className={staticLabels ? 'visually-hidden' : undefined}>
      <tr>
        {status === 'open' ? (
          heading(
            'Priority',
            columns.priority,
            'Ascending Priority enables drag ordering',
          )
        ) : (
          <th scope="col">Priority</th>
        )}
        {heading('Title', columns.title)}
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
