import { Link, useNavigate } from 'react-router';
import { api } from '../api';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { useActionItemQueue } from '../hooks/useActionItemQueue';
import { ActionItemQueueTable } from '../components/ActionItemQueueTable';
import { actionItemTags } from '../utils/actionItems';
import {
  ACTION_ITEM_STATUSES,
  actionItemSortOptions,
  defaultActionItemSort,
} from '../constants';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { parseViewField } from '../utils/viewPreferences';
import { ActionItemProjectTabs } from '../components/ActionItemProjects';
import { projectScope, projectScopeFields } from '../utils/actionItemProjects';
import { ActionItemDeadlineWindow } from '../components/ActionItemDeadlines';
import { FilterCheckbox } from '../components/FilterCheckbox';

export function ActionItemsIndexPage() {
  const navigate = useNavigate();
  const preferences = useViewPreferences('actionItems');
  const {
    status,
    sort,
    q: queryInput,
    project,
    unassigned,
    due_within_hours: dueHoursInput,
    tags: tagsInput,
  } = preferences.values;
  const query = useDebouncedValue(queryInput.trim());
  const tags = useDebouncedValue(tagsInput.trim());
  const dueHours = useDebouncedValue(dueHoursInput);
  const criteriaPending =
    queryInput.trim() !== query ||
    tagsInput.trim() !== tags ||
    dueHoursInput !== dueHours;
  const queue = useActionItemQueue({
    source: api.actionItems,
    removeRow: api.actionItems.remove,
    filters: {
      status,
      sort,
      q: query || undefined,
      project: project || undefined,
      ...(unassigned ? { unassigned: true } : {}),
      ...(dueHours !== null ? { due_within_hours: dueHours } : {}),
      tags: actionItemTags(tags),
    },
    criteria: JSON.stringify([
      status,
      sort,
      query,
      project,
      unassigned,
      dueHours,
      tags,
    ]),
    viewKey: JSON.stringify([
      status,
      sort,
      queryInput,
      project,
      unassigned,
      dueHoursInput,
      tagsInput,
    ]),
    reorderableView: status === 'open' && sort === 'manual',
    projectAssignment: true,
    criteriaPending,
    pagination: { ...preferences.pagination, enabled: !criteriaPending },
  });
  const { freezeControls } = queue;
  return (
    <div className="action-items-index-page">
      <div className="page-header">
        <h2 className="page-title">Action items</h2>
        <Link
          className="btn btn-primary"
          style={{ textDecoration: 'none' }}
          to={
            project
              ? `/action-items/new?${new URLSearchParams({ project })}`
              : '/action-items/new'
          }
        >
          New action item
        </Link>
      </div>
      <ActionItemProjectTabs
        scope={projectScope(project, unassigned)}
        onChange={(scope) => preferences.setFields(projectScopeFields(scope))}
        disabled={freezeControls}
        paused={queue.busy || Boolean(queue.snapshot)}
        dropTargetsRef={queue.projectTabsRef}
        dropProject={queue.snapshot?.project}
        dragging={Boolean(queue.snapshot) && !queue.busy}
        toolbarAccessory={
          <div
            className="sub-tabs"
            role="tablist"
            aria-label="Action item status"
          >
            {ACTION_ITEM_STATUSES.map(([value, label]) => (
              <button
                key={value}
                role="tab"
                aria-selected={status === value}
                className={status === value ? 'active' : ''}
                disabled={freezeControls}
                onClick={() => {
                  preferences.setFields({
                    status: value,
                    sort: defaultActionItemSort(value),
                  });
                }}
              >
                {label}
              </button>
            ))}
          </div>
        }
        beforeTabs={
          <>
            <div className="profile-filters action-item-filters">
              <label>
                <span className="form-label">Search action items</span>
                <input
                  className="input"
                  type="search"
                  maxLength={1000}
                  value={queryInput}
                  disabled={freezeControls}
                  onChange={(event) =>
                    preferences.setField('q', event.target.value)
                  }
                  placeholder="Search title or description…"
                />
              </label>
              <label>
                <span className="form-label">Tags</span>
                <input
                  className="input"
                  value={tagsInput}
                  disabled={freezeControls}
                  onChange={(event) =>
                    preferences.setField('tags', event.target.value)
                  }
                  placeholder="Tags, comma-separated"
                />
              </label>
              <label>
                <span className="form-label">Sort</span>
                <select
                  className="input"
                  value={sort}
                  disabled={freezeControls}
                  onChange={(event) =>
                    preferences.setField(
                      'sort',
                      parseViewField('actionItems', 'sort', event.target.value),
                    )
                  }
                >
                  {actionItemSortOptions(status).map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <FilterCheckbox
                checked={unassigned}
                disabled={freezeControls || Boolean(project)}
                title={
                  project
                    ? 'Select All projects to filter unassigned items.'
                    : undefined
                }
                onChange={(event) =>
                  preferences.setFields({
                    project: '',
                    unassigned: event.target.checked,
                  })
                }
              >
                Unassigned only
              </FilterCheckbox>
              <ActionItemDeadlineWindow
                hours={dueHoursInput}
                onChange={(hours) =>
                  preferences.setField('due_within_hours', hours)
                }
                disabled={freezeControls}
              />
            </div>
            {(status !== 'open' || sort !== 'manual') && (
              <p className="text-muted-sm">
                To drag items into order, use Open with Manual order; search and
                filters can stay applied.
              </p>
            )}
          </>
        }
      />
      <ActionItemQueueTable
        queue={queue}
        status={status}
        showDueDate
        onEdit={(item) => navigate(`/action-items/${item.id}?edit=1`)}
      />
    </div>
  );
}
