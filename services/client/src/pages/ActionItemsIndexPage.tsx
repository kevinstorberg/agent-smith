import { useId, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { useActionItemGroupedQueue } from '../hooks/useActionItemGroupedQueue';
import { ActionItemGroupedQueue } from '../components/ActionItemGroupedQueue';
import {
  EpicCreationRetry,
  NewEpicControl,
} from '../components/ActionItemEpicControls';
import { actionItemTags } from '../utils/actionItems';
import {
  ACTION_ITEM_QUEUE_KIND_OPTIONS,
  ACTION_ITEM_STATUSES,
  defaultActionItemSort,
} from '../constants';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { ActionItemProjectTabs } from '../components/ActionItemProjects';
import { projectScope, projectScopeFields } from '../utils/actionItemProjects';
import { ActionItemDeadlineWindow } from '../components/ActionItemDeadlines';
import { FilterCheckbox } from '../components/FilterCheckbox';
import { ButtonLink } from '../components/ButtonLink';
import { parseViewField } from '../utils/viewPreferences';
import './actionItemsIndex.css';

export function ActionItemsIndexPage() {
  const navigate = useNavigate();
  const preferences = useViewPreferences('actionItems');
  const {
    kind,
    status,
    sort,
    q: queryInput,
    project,
    unassigned,
    priority_only: priorityOnly,
    due_within_hours: dueHoursInput,
    tags: tagsInput,
  } = preferences.values;
  const filterId = useId();
  const [filtersOpen, setFiltersOpen] = useState(false);
  const activeFilters = [
    ...(tagsInput.trim() ? [`Tags: ${tagsInput.trim()}`] : []),
    ...(unassigned ? ['No project'] : []),
    ...(priorityOnly ? ['Priority only'] : []),
    ...(dueHoursInput !== null
      ? [`Due within ${dueHoursInput} hours, including overdue`]
      : []),
  ];
  const query = useDebouncedValue(queryInput.trim());
  const tags = useDebouncedValue(tagsInput.trim());
  const dueHours = useDebouncedValue(dueHoursInput);
  const criteriaPending =
    queryInput.trim() !== query ||
    tagsInput.trim() !== tags ||
    dueHoursInput !== dueHours;
  const queue = useActionItemGroupedQueue({
    filters: {
      ...(kind !== 'all' ? { kind } : {}),
      status,
      sort,
      q: query || undefined,
      project: project || undefined,
      ...(unassigned ? { unassigned: true } : {}),
      ...(priorityOnly ? { priority_only: true } : {}),
      ...(dueHours !== null ? { due_within_hours: dueHours } : {}),
      tags: actionItemTags(tags),
    },
    criteria: JSON.stringify([
      kind,
      status,
      sort,
      query,
      project,
      unassigned,
      priorityOnly,
      dueHours,
      tags,
    ]),
    viewKey: JSON.stringify([
      kind,
      status,
      sort,
      queryInput,
      project,
      unassigned,
      priorityOnly,
      dueHoursInput,
      tagsInput,
    ]),
    reorderableView: status === 'open' && sort === 'manual',
    criteriaPending,
    pagination: { ...preferences.pagination, enabled: !criteriaPending },
  });
  const { freezeControls } = queue;
  const searchControls = (
    <div className="filters resource-controls action-items-primary-filters">
      <label className="action-items-search">
        <span className="form-label">Search action items</span>
        <input
          className="input"
          type="search"
          maxLength={1000}
          value={queryInput}
          disabled={freezeControls}
          onChange={(event) => preferences.setField('q', event.target.value)}
          placeholder="Search title or description…"
        />
      </label>
      <label className="action-items-status-filter">
        <span className="form-label">Status</span>
        <select
          className="input"
          value={status}
          disabled={freezeControls}
          onChange={(event) => {
            const value = parseViewField(
              'actionItems',
              'status',
              event.target.value,
            );
            preferences.setFields({
              status: value,
              sort: defaultActionItemSort(value),
            });
          }}
        >
          {ACTION_ITEM_STATUSES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="btn action-items-filter-toggle"
        aria-expanded={filtersOpen}
        aria-controls={filterId}
        disabled={freezeControls}
        onClick={() => setFiltersOpen((open) => !open)}
      >
        More filters{activeFilters.length ? ` (${activeFilters.length})` : ''}
        <span aria-hidden="true">{filtersOpen ? '⌃' : '⌄'}</span>
      </button>
    </div>
  );
  return (
    <div className="action-items-index-page">
      <div className="page-header">
        <h2 className="page-title">Action items</h2>
        <div className="action-items-page-actions">
          <ButtonLink
            className="action-proposals-link"
            to="/action-items/proposals?status=pending"
          >
            Proposed action items
          </ButtonLink>
          <NewEpicControl queue={queue} />
          <Link
            className="btn btn-primary"
            to={
              project
                ? `/action-items/new?${new URLSearchParams({ project })}`
                : '/action-items/new'
            }
          >
            New action item
          </Link>
        </div>
      </div>
      <EpicCreationRetry queue={queue} />
      <section
        className="action-items-filter-region"
        aria-label="Action item filters"
      >
        {searchControls}
        <div
          className="action-items-search-and-filters"
          hidden={!activeFilters.length && !filtersOpen}
        >
          {activeFilters.length > 0 && (
            <div
              className="action-items-active-filters"
              aria-label="Active filters"
            >
              <p>{activeFilters.join(' · ')}</p>
              <button
                type="button"
                className="inline-clear"
                disabled={freezeControls}
                onClick={() =>
                  preferences.setFields({
                    tags: '',
                    unassigned: false,
                    priority_only: false,
                    due_within_hours: null,
                  })
                }
              >
                Clear filters
              </button>
            </div>
          )}
          <div
            id={filterId}
            className="action-item-filters action-items-advanced-filters"
            role="group"
            aria-label="Filter action items"
            hidden={!filtersOpen}
          >
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
              No project
            </FilterCheckbox>
            <ActionItemDeadlineWindow
              hours={dueHoursInput}
              onChange={(hours) =>
                preferences.setField('due_within_hours', hours)
              }
              disabled={freezeControls}
            />
          </div>
        </div>
      </section>
      <ActionItemProjectTabs
        compactManagement
        scope={projectScope(project, unassigned)}
        onChange={(scope) => preferences.setFields(projectScopeFields(scope))}
        disabled={freezeControls}
        paused={queue.busy || queue.editing || Boolean(queue.snapshot)}
        dropTargetsRef={queue.projectTabsRef}
        dropProject={queue.snapshot?.project}
        dragging={Boolean(queue.snapshot) && !queue.busy}
        toolbarAccessory={
          <div
            className="action-items-view-filter"
            role="group"
            aria-label="Show"
          >
            <span className="form-label">Show</span>
            <div className="sub-tabs">
              {ACTION_ITEM_QUEUE_KIND_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={kind === option.value}
                  className={kind === option.value ? 'active' : ''}
                  disabled={freezeControls}
                  onClick={() => preferences.setField('kind', option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <FilterCheckbox
              checked={priorityOnly}
              disabled={freezeControls}
              onChange={(event) =>
                preferences.setField('priority_only', event.target.checked)
              }
            >
              Priority only
            </FilterCheckbox>
          </div>
        }
      />
      {queue.membershipNotice && (
        <p role="status" className="action-items-membership-notice">
          <Link to={`/action-items/${queue.membershipNotice.itemId}`}>
            {queue.membershipNotice.title}
          </Link>{' '}
          moved out of Epic “{queue.membershipNotice.epicTitle}”. It is
          available in All or Action Items.{' '}
          <button
            type="button"
            className="inline-clear"
            onClick={queue.clearMembershipNotice}
          >
            Dismiss
          </button>
        </p>
      )}
      {queue.created &&
        !queue.items.some(
          (root) => root.kind === 'epic' && root.epic.id === queue.created?.id,
        ) && (
          <p role="status">
            Epic “{queue.created.title}” created.{' '}
            <button
              className="btn btn-sm"
              disabled={queue.freezeControls}
              onClick={() =>
                queue.showCreated((position) => {
                  preferences.setFields({
                    kind: 'all',
                    status: 'open',
                    sort: 'manual',
                    q: '',
                    project: '',
                    unassigned: false,
                    priority_only: false,
                    due_within_hours: null,
                    tags: '',
                  });
                  preferences.setField(
                    'offset',
                    Math.floor((position - 1) / queue.limit) * queue.limit,
                  );
                })
              }
            >
              Show Epic
            </button>
          </p>
        )}
      <ActionItemGroupedQueue
        queue={queue}
        sort={sort}
        onSort={(value) => preferences.setField('sort', value)}
        status={status}
        onEdit={(item) => navigate(`/action-items/${item.id}?edit=1`)}
      />
    </div>
  );
}
