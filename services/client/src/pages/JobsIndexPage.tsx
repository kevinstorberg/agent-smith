import { useNavigate } from 'react-router';
import { api } from '../api';
import type { Job } from '../api';
import { Pagination } from '../components/Pagination';
import { FilterBar } from '../components/FilterBar';
import { DateCell } from '../components/table';
import { SortableHeader } from '../components/table/SortableHeader';
import { ScrollableTable } from '../components/ScrollableTable';
import { JobScheduleButton } from '../components/JobScheduleButton';
import { usePagination } from '../hooks/usePagination';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { formatSchedule } from '../utils/schedule';
import { useViewPreferences } from '../hooks/useViewPreferences';
import {
  JOB_SORT_COLUMNS,
  SCHEDULING_OPTIONS,
  parseViewField,
} from '../utils/viewPreferences';
import './jobsSorting.css';

export function JobsIndexPage() {
  const navigate = useNavigate();
  const preferences = useViewPreferences('jobs');
  const { q: query, schedule_enabled: scheduling, sort } = preferences.values;
  const debouncedQuery = useDebouncedValue(query);

  const {
    items,
    setItems,
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
  } = usePagination<Job>(
    (l, o) =>
      api.jobs.list({
        limit: l,
        offset: o,
        q: debouncedQuery || undefined,
        schedule_enabled: scheduling ? scheduling === 'true' : undefined,
        sort,
      }),
    [debouncedQuery, scheduling, sort],
    10,
    { ...preferences.pagination, enabled: debouncedQuery === query },
  );
  usePolling(() => refresh({ showLoading: false }));
  const updating =
    loading || query !== debouncedQuery || (!error && !dataCurrent);
  const readable = dataCurrent && !updating;
  const accepted = readable && !error;
  const schedulingChanged = (updated: Job) => {
    refresh({ showLoading: false });
    setItems((current) =>
      current
        .map((job) =>
          job.id === updated.id
            ? {
                ...job,
                schedule_enabled: updated.schedule_enabled,
                version: updated.version,
                updated_at: updated.updated_at,
              }
            : job,
        )
        .filter(
          (job) =>
            !scheduling || job.schedule_enabled === (scheduling === 'true'),
        ),
    );
  };

  return (
    <div className="jobs-page">
      <div className="page-header">
        <h2 className="page-title">Jobs</h2>
        <button
          className="btn btn-primary"
          onClick={() => navigate('/jobs/new')}
        >
          + New Job
        </button>
      </div>

      <FilterBar
        nameValue={query}
        onNameChange={(value) => preferences.setField('q', value)}
        namePlaceholder="Search jobs..."
      >
        <label>
          <span className="form-label">Scheduling</span>
          <select
            aria-label="Scheduling"
            value={scheduling}
            onChange={(event) =>
              preferences.setField(
                'schedule_enabled',
                parseViewField('jobs', 'schedule_enabled', event.target.value),
              )
            }
          >
            {SCHEDULING_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </FilterBar>
      {error && (
        <p role="alert">
          Could not refresh jobs.{' '}
          <button
            className="btn btn-sm"
            disabled={loading}
            onClick={() => refresh()}
          >
            Retry
          </button>
        </p>
      )}
      {initialLoading && (
        <div className="loading" role="status">
          Loading...
        </div>
      )}
      <span className="visually-hidden" role="status">
        {!initialLoading && updating ? 'Updating jobs…' : ''}
      </span>
      <div className="jobs-table">
        <ScrollableTable
          label="Jobs list"
          className="jobs-list-table"
          busy={updating && (loading || !error)}
          emptyState={
            accepted && items.length === 0 ? (
              <p className="loading" role="status">
                No jobs found
              </p>
            ) : undefined
          }
        >
          <thead>
            <tr>
              <SortableHeader
                sort={sort}
                column={JOB_SORT_COLUMNS.name}
                current={accepted}
                onSort={(value) => preferences.setField('sort', value)}
              >
                Name
              </SortableHeader>
              <th>Schedule</th>
              <SortableHeader
                sort={sort}
                column={JOB_SORT_COLUMNS.updated}
                current={accepted}
                onSort={(value) => preferences.setField('sort', value)}
              >
                Last Updated
              </SortableHeader>
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(!error || dataCurrent) &&
              items.map((job) => (
                <tr
                  key={job.id}
                  {...makeRowClickable(() => navigate(`/jobs/${job.id}`))}
                  style={{ cursor: 'pointer' }}
                >
                  <td>{job.name}</td>
                  <td>
                    <span className="tag">
                      {formatSchedule(job.schedule_config)}
                    </span>
                    {!job.schedule_enabled && (
                      <span className="tag tag-warning">Paused</span>
                    )}
                  </td>
                  <td>
                    <DateCell date={job.updated_at} />
                  </td>
                  <td className="text-right">
                    <JobScheduleButton
                      job={job}
                      small
                      disabled={!readable}
                      onChanged={schedulingChanged}
                    />
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
          onLimitChange={(newLimit) => {
            setLimit(newLimit);
            setOffset(0);
          }}
          disabled={loading}
        />
      )}
    </div>
  );
}
