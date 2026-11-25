import { useId, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { useActionItemGroupedQueue } from '../hooks/useActionItemGroupedQueue';
import { ActionItemGroupedQueue } from '../components/ActionItemGroupedQueue';
import { NewEpicControl } from '../components/ActionItemEpicControls';
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
    due_within_hours: dueHoursInput,
    tags: tagsInput,
  } = preferences.values;
  const filterId = useId();
  const [filtersOpen, setFiltersOpen] = useState(false);
  const activeFilters = [
    ...(tagsInput.trim() ? [`Tags: ${tagsInput.trim()}`] : []),
    ...(unassigned ? ['Unassigned only'] : []),
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
      dueHoursInput,
      tagsInput,
    ]),
    reorderableView: status === 'open' && sort === 'manual',
    criteriaPending,
    pagination: { ...preferences.pagination, enabled: !criteriaPending },
  });
  const { freezeControls } = queue;
  const searchControls = (
    <div className="action-items-searchbar">
      <label className="action-items-search">
        <span className="visually-hidden">Search action items</span>
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
      <button
        type="button"
        className="btn action-items-filter-toggle"
        aria-expanded={filtersOpen}
        aria-controls={filterId}
        disabled={freezeControls}
        onClick={() => setFiltersOpen((open) => !open)}
      >
        Filters
        {activeFilters.length ? ` (${activeFilters.length})` : ''}
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
          <div className="action-items-toolbar-controls">
            {searchControls}
            <label className="action-items-type-filter">
              <span className="form-label">Item type</span>
              <select
                className="input"
                value={kind}
                disabled={freezeControls}
                onChange={(event) =>
                  preferences.setField(
                    'kind',
                    parseViewField('actionItems', 'kind', event.target.value),
                  )
                }
              >
                {ACTION_ITEM_QUEUE_KIND_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
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
          </div>
        }
        beforeTabs={
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
          </div>
        }
      />
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
