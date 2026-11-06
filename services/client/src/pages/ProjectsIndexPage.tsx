import { useNavigate } from 'react-router';
import { ButtonLink } from '../components/ButtonLink';
import { api } from '../api';
import { FilterBar } from '../components/FilterBar';
import { Pagination } from '../components/Pagination';
import { ScrollableTable } from '../components/ScrollableTable';
import { DateCell } from '../components/table';
import { SortableHeader } from '../components/table/SortableHeader';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { makeRowClickable } from '../utils/a11y';
import { projectLabel } from '../utils/actionItemProjects';
import { PROJECT_SORT_COLUMNS } from '../utils/viewPreferences';
import './projects.css';

export function ProjectsIndexPage() {
  const navigate = useNavigate();
  const preferences = useViewPreferences('projects');
  const { q, sort } = preferences.values;
  const query = useDebouncedValue(q.trim());
  const {
    items,
    total,
    loading,
    initialLoading,
    error,
    dataCurrent,
    limit,
    offset,
    setLimit,
    setOffset,
    refresh,
  } = usePagination(
    (limit, offset) =>
      api.projects.list({ q: query || undefined, sort, limit, offset }),
    [query, sort],
    10,
    { ...preferences.pagination, enabled: query === q.trim() },
  );
  usePolling(() => refresh({ showLoading: false }));

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Projects</h2>
        <ButtonLink className="btn-primary" to="/projects/new">
          + New project
        </ButtonLink>
      </div>
      <FilterBar
        nameValue={q}
        onNameChange={(value) => preferences.setField('q', value)}
        nameLabel="Search projects"
        namePlaceholder="Search name or description..."
      />
      {initialLoading && <div className="loading">Loading projects...</div>}
      {error && (
        <div className="card" role="alert">
          <p>Could not load projects.</p>
          <button type="button" className="btn" onClick={() => refresh()}>
            Retry
          </button>
        </div>
      )}
      <div className="table-container">
        <ScrollableTable
          label="Projects list"
          tableLabel="Projects"
          className="projects-table"
          busy={!dataCurrent && !error}
          emptyState={
            !loading && !error && dataCurrent && !items.length ? (
              <p className="loading">
                {query
                  ? 'No projects match your search.'
                  : 'No projects yet. Create a project to organize your action items.'}
              </p>
            ) : undefined
          }
        >
          <colgroup>
            <col className="project-name-column" />
            <col />
            <col className="project-date-column" />
          </colgroup>
          <thead>
            <tr>
              {(['name', 'description', 'updated'] as const).map((column) => (
                <SortableHeader
                  key={column}
                  sort={sort}
                  column={PROJECT_SORT_COLUMNS[column]}
                  current={dataCurrent}
                  onSort={(value) => preferences.setField('sort', value)}
                >
                  {
                    {
                      name: 'Name',
                      description: 'Description',
                      updated: 'Updated',
                    }[column]
                  }
                </SortableHeader>
              ))}
            </tr>
          </thead>
          <tbody>
            {!error &&
              items.map((project) => (
                <tr
                  key={project.id}
                  {...makeRowClickable(() =>
                    navigate(`/projects/${project.id}`),
                  )}
                  style={{ cursor: 'pointer' }}
                >
                  <td>{projectLabel(project.name)}</td>
                  <td>
                    <div className="project-description-preview">
                      {project.description || (
                        <span className="text-muted">No description</span>
                      )}
                    </div>
                  </td>
                  <td>
                    <DateCell date={project.updated_at} />
                  </td>
                </tr>
              ))}
          </tbody>
        </ScrollableTable>
      </div>
      {!error && (
        <Pagination
          total={total}
          limit={limit}
          offset={offset}
          onPageChange={setOffset}
          onLimitChange={setLimit}
          disabled={loading}
        />
      )}
    </div>
  );
}
