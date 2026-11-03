import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { api } from '../api';
import type { ActionItemFilters, ActionItemSort } from '../api';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { useActionItemQueue } from '../hooks/useActionItemQueue';
import { ActionItemQueueTable } from '../components/ActionItemQueueTable';
import { actionItemTags } from '../utils/actionItems';

const TABS = [['open', 'Open'], ['completed', 'Completed'], ['all', 'All']] as const;
type Status = NonNullable<ActionItemFilters['status']>;

export function ActionItemsIndexPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<Status>('open');
  const [sort, setSort] = useState<ActionItemSort>('manual');
  const [queryInput, setQueryInput] = useState('');
  const [projectInput, setProjectInput] = useState('');
  const [tagsInput, setTagsInput] = useState('');
  const query = useDebouncedValue(queryInput.trim());
  const project = useDebouncedValue(projectInput.trim());
  const tags = useDebouncedValue(tagsInput.trim());
  const criteriaPending = queryInput.trim() !== query || projectInput.trim() !== project || tagsInput.trim() !== tags;
  const queue = useActionItemQueue({ source: api.actionItems,
    filters: { status, sort, q: query || undefined, project: project || undefined, tags: actionItemTags(tags) },
    criteria: JSON.stringify([status, sort, query, project, tags]),
    viewKey: JSON.stringify([status, sort, queryInput, projectInput, tagsInput]),
    reorderableView: status === 'open' && sort === 'manual', criteriaPending,
  });
  const { freezeControls } = queue;
  return <div>
    <div className="page-header"><h2 className="page-title">Action items</h2>
      <Link className="btn btn-primary" style={{ textDecoration: 'none' }} to="/action-items/new">New action item</Link>
    </div>
    <div className="sub-tabs" role="tablist" aria-label="Action item status">
      {TABS.map(([value, label]) => <button key={value} role="tab" aria-selected={status === value}
        className={status === value ? 'active' : ''} disabled={freezeControls} onClick={() => {
          setStatus(value); setSort(value === 'open' ? 'manual' : value === 'completed' ? 'completed' : 'newest');
        }}>{label}</button>)}
    </div>
    <div className="profile-filters">
      <label><span className="form-label">Search action items</span><input className="input" type="search" maxLength={1000}
        value={queryInput} disabled={freezeControls} onChange={event => setQueryInput(event.target.value)} placeholder="Search title or description…" /></label>
      <label><span className="form-label">Project</span><input className="input" maxLength={200} value={projectInput}
        disabled={freezeControls} onChange={event => setProjectInput(event.target.value)} placeholder="All projects" /></label>
      <label><span className="form-label">Tags</span><input className="input" value={tagsInput} disabled={freezeControls}
        onChange={event => setTagsInput(event.target.value)} placeholder="Tags, comma-separated" /></label>
      <label><span className="form-label">Sort</span><select className="input" value={sort} disabled={freezeControls}
        onChange={event => setSort(event.target.value as ActionItemSort)}>
        {status === 'open' && <option value="manual">Manual order</option>}
        {status === 'completed' && <option value="completed">Recently completed</option>}
        <option value="newest">Newest</option><option value="updated">Recently updated</option><option value="title">Title A–Z</option>
      </select></label>
    </div>
    {(status !== 'open' || sort !== 'manual') && <p className="text-muted-sm">To drag items into order, use Open with Manual order; search and filters can stay applied.</p>}
    <ActionItemQueueTable queue={queue} status={status} onEdit={item => navigate(`/action-items/${item.id}?edit=1`)} />
  </div>;
}
