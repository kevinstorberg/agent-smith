import { useNavigate } from 'react-router';
import { api } from '../api';
import type { Job } from '../api';
import { Pagination } from '../components/Pagination';
import { DateCell } from '../components/table';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { makeRowClickable } from '../utils/a11y';
import { formatSchedule } from '../utils/schedule';

export function JobsIndexPage() {
  const navigate = useNavigate();

  const { items, total, loading, limit, offset, setLimit, setOffset, refresh } = usePagination<Job>(
    (l, o) => api.jobs.list({ limit: l, offset: o }),
  );
  usePolling(() => refresh({ showLoading: false }));

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">Jobs</h2>
        <button className="btn btn-primary" onClick={() => navigate('/jobs/new')}>
          + New Job
        </button>
      </div>

      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Schedule</th>
            <th>Last Updated</th>
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
              <td><span className="tag">{formatSchedule(job.schedule_config)}</span></td>
              <td><DateCell date={job.updated_at} /></td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr><td colSpan={3} className="loading">No jobs found</td></tr>
          )}
        </tbody>
      </table>

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
