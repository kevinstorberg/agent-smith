import { useEffect, useRef } from 'react';
import { api } from '../api';
import type { Job } from '../api';
import { useApiMutation } from '../hooks/useApiMutation';

export function JobScheduleButton({ job, onChanged, disabled = false, small = false }: {
  job: Pick<Job, 'id' | 'name' | 'schedule_enabled'>;
  onChanged: (updated: Job) => void;
  disabled?: boolean;
  small?: boolean;
}) {
  const mounted = useRef(false);
  const writing = useRef(false);
  const latest = useRef({ id: job.id, onChanged });
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { latest.current = { id: job.id, onChanged }; }, [job.id, onChanged]);
  const change = useApiMutation({
    mutationFn: async (id: number, enabled: boolean) => {
      const updated = await api.jobs.setScheduling(id, { schedule_enabled: enabled });
      if (updated.id !== id) throw new Error('The server returned a different job.');
      return updated;
    },
    onSuccess: updated => {
      if (mounted.current && latest.current.id === updated.id) latest.current.onChanged(updated);
    },
    onError: () => undefined,
  });
  const label = job.schedule_enabled ? 'Pause automatic runs' : 'Resume automatic runs';
  return <div className="job-schedule-action">
    <button type="button" className={`btn${small ? ' btn-sm' : ''}`} aria-label={`${label} for ${job.name}`}
      disabled={disabled || change.loading} onKeyDown={event => event.stopPropagation()}
      onClick={event => {
        event.stopPropagation();
        if (disabled || writing.current) return;
        writing.current = true;
        change.mutate(job.id, !job.schedule_enabled).finally(() => { writing.current = false; });
      }}>{change.loading ? 'Saving...' : label}</button>
    {change.error && <span className="text-muted-sm" role="alert">Could not change automatic runs. Try again.</span>}
  </div>;
}
