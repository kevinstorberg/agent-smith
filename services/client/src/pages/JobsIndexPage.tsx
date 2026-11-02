import { useNavigate } from 'react-router';
import { api } from '../api';
import type { Job } from '../api';
import { Pagination } from '../components/Pagination';
import { DateCell } from '../components/table';
import { JobScheduleButton } from '../components/JobScheduleButton';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { formatSchedule } from '../utils/schedule';

export function JobsIndexPage() {
  const navigate = useNavigate();

  const { items, setItems, total, loading, error, limit, offset, setLimit, setOffset, refresh } = usePagination<Job>(
    (l, o) => api.jobs.list({ limit: l, offset: o }),
  );
  usePolling(() => refresh({ showLoading: false }));
  const schedulingChanged = (updated: Job) => {
    refresh({ showLoading: false });
    setItems(current => current.map(job => job.id === updated.id ? { ...job, schedule_enabled: updated.schedule_enabled,
      version: updated.version, updated_at: updated.updated_at } : job));
  };

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Jobs</h2>
        <button className="btn btn-primary" onClick={() => navigate('/jobs/new')}>
          + New Job
        </button>
      </div>

      {error && <p role="alert">Could not refresh jobs. The current list is kept. <button className="btn btn-sm" onClick={() => refresh({ showLoading: false })}>Retry</button></p>}
      <div className="jobs-table" role="region" aria-label="Jobs list" tabIndex={0}><table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Schedule</th>
            <th>Last Updated</th>
            <th className="text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map(job => (
            <tr
              key={job.id}
              {...makeRowClickable(() => navigate(`/jobs/${job.id}`))}
              style={{ cursor: 'pointer' }}
            >
              <td>{job.name}</td>
              <td><span className="tag">{formatSchedule(job.schedule_config)}</span>{!job.schedule_enabled && <span className="tag tag-warning">Paused</span>}</td>
              <td><DateCell date={job.updated_at} /></td>
              <td className="text-right"><JobScheduleButton job={job} small onChanged={schedulingChanged} /></td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr><td colSpan={4} className="loading">No jobs found</td></tr>
          )}
        </tbody>
      </table></div>

      <Pagination
        total={total}
        limit={limit}
        offset={offset}
        onPageChange={setOffset}
        onLimitChange={newLimit => { setLimit(newLimit); setOffset(0); }}
      />
    </div>
  );
}
