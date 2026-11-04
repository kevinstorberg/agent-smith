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

export function ActionItemsIndexPage() {
  const navigate = useNavigate();
  const preferences = useViewPreferences('actionItems');
  const {
    status,
    sort,
    q: queryInput,
    project: projectInput,
    tags: tagsInput,
  } = preferences.values;
  const query = useDebouncedValue(queryInput.trim());
  const project = useDebouncedValue(projectInput.trim());
  const tags = useDebouncedValue(tagsInput.trim());
  const criteriaPending =
    queryInput.trim() !== query ||
    projectInput.trim() !== project ||
    tagsInput.trim() !== tags;
  const queue = useActionItemQueue({
    source: api.actionItems,
    removeRow: api.actionItems.remove,
    filters: {
      status,
      sort,
      q: query || undefined,
      project: project || undefined,
      tags: actionItemTags(tags),
    },
    criteria: JSON.stringify([status, sort, query, project, tags]),
    viewKey: JSON.stringify([
      status,
      sort,
      queryInput,
      projectInput,
      tagsInput,
    ]),
    reorderableView: status === 'open' && sort === 'manual',
    criteriaPending,
    pagination: { ...preferences.pagination, enabled: !criteriaPending },
  });
  const { freezeControls } = queue;
  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Action items</h2>
        <Link
          className="btn btn-primary"
          style={{ textDecoration: 'none' }}
          to="/action-items/new"
        >
          New action item
        </Link>
      </div>
      <div className="sub-tabs" role="tablist" aria-label="Action item status">
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
      <div className="profile-filters">
        <label>
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
        <label>
          <span className="form-label">Project</span>
          <input
            className="input"
            maxLength={200}
            value={projectInput}
            disabled={freezeControls}
            onChange={(event) =>
              preferences.setField('project', event.target.value)
            }
            placeholder="All projects"
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
      </div>
      {(status !== 'open' || sort !== 'manual') && (
        <p className="text-muted-sm">
          To drag items into order, use Open with Manual order; search and
          filters can stay applied.
        </p>
      )}
      <ActionItemQueueTable
        queue={queue}
        status={status}
        onEdit={(item) => navigate(`/action-items/${item.id}?edit=1`)}
      />
    </div>
  );
}
