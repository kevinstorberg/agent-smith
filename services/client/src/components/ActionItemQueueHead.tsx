import type { ActionItemSort } from '../api';
import { ACTION_ITEM_SORT_COLUMNS } from '../constants';
import { columnDirection } from '../utils/tableSorting';
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
}: {
  sort: ActionItemSort;
  onSort: (sort: ActionItemSort) => void;
  current: boolean;
  disabled: boolean;
  status: string;
  showProject?: boolean;
  showDueDate?: boolean;
  showUpdated?: boolean;
}) {
  const sorting = { sort, onSort, current, disabled };
  const columns = ACTION_ITEM_SORT_COLUMNS;
  return (
    <thead>
      <tr>
        {status === 'open' ? (
          <SortableHeader
            {...sorting}
            column={columns.priority}
            title="Ascending Priority enables drag ordering"
          >
            Priority
          </SortableHeader>
        ) : (
          <th scope="col">Priority</th>
        )}
        <SortableHeader {...sorting} column={columns.title}>
          Title
        </SortableHeader>
        {showProject ? (
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
        ) : (
          <SortableHeader {...sorting} column={columns.tags}>
            Tags
          </SortableHeader>
        )}
        {showDueDate && (
          <SortableHeader {...sorting} column={columns.due}>
            Due date
          </SortableHeader>
        )}
        {showUpdated && (
          <SortableHeader {...sorting} column={columns.updated}>
            Updated
          </SortableHeader>
        )}
        <th scope="col">Actions</th>
      </tr>
    </thead>
  );
}
