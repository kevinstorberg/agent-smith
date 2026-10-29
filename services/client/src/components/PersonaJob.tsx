import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { GraphJob, JobRunResult } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { usePolling } from '../hooks/usePolling';
import { personaOutcome } from '../utils/personaOutcome';

function source(job: GraphJob): string | undefined {
  const inputs = job.input_params.graph_inputs as Record<string, unknown> | undefined;
  return typeof inputs?.source === 'string' ? inputs.source : undefined;
}

export function PersonaJob({ onChanged }: { onChanged: () => void }) {
  const read = useCallback(() => api.jobs.forGraph('persona'), []);
  const { data, loading, error, refresh } = useApiRead(read);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ jobId: number; value: JobRunResult } | null>(null);
  const [failed, setFailed] = useState(false);
  const inFlight = useRef(false);
  // LIVE view refresh: filters may change while the job runs.
  const onChangedRef = useRef(onChanged);
  useEffect(() => { onChangedRef.current = onChanged; }, [onChanged]);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const jobs = data?.items || [];
  const selected = jobs.find(job => job.id === selectedId)
    || jobs.find(job => job.runs_on_device && !source(job))
    || jobs.find(job => job.runs_on_device) || jobs[0];
  usePolling(() => refresh({ showLoading: false }), { enabled: !running });

  const run = async () => {
    if (!selected || inFlight.current) return;
    inFlight.current = true;
    setRunning(true); setResult(null); setFailed(false);
    try {
      const value = await api.jobs.runNow(selected.id);
      if (mounted.current) { setResult({ jobId: selected.id, value }); onChangedRef.current(); }
    } catch {
      if (mounted.current) setFailed(true);
    } finally {
      inFlight.current = false;
      if (mounted.current) setRunning(false);
    }
  };

  return <div className="persona-job-controls">
    <button className="btn btn-primary" disabled={loading || Boolean(error) || !selected || running} onClick={run}>{running ? 'Running personas...' : 'Run personas'}</button>
    {loading && !data ? <span className="persona-job-feedback text-muted-sm">Checking persona jobs...</span> : error ? <span className="persona-job-feedback" role="alert">
      Could not check persona jobs. <button className="btn btn-sm" onClick={() => refresh()}>Retry job check</button>
    </span> : !selected ? <span className="persona-job-feedback text-muted-sm">
      Automatic profile updates are not configured. <Link className="text-link" to="/jobs/new?graph=persona">Create persona job</Link> or <Link className="text-link" to="/jobs">manage jobs</Link>.
    </span> : <>
      {jobs.length > 1 && <select className="input persona-job-select" aria-label="Persona job" value={selected.id} disabled={running}
        onChange={event => { setSelectedId(Number(event.target.value)); setResult(null); setFailed(false); }}>
        {jobs.map(job => <option key={job.id} value={job.id}>{job.name}</option>)}
      </select>}
      {(source(selected) || !selected.runs_on_device) && <span className="persona-job-feedback text-muted-sm">
        {source(selected) && `Connection: ${source(selected)}. `}{!selected.runs_on_device && 'This job does not run automatically on this device. '}
        <Link className="text-link" to={`/jobs/${selected.id}`}>Job settings</Link>
      </span>}
      {running && <span className="persona-job-feedback" role="status">Reviewing saved context. <Link className="text-link" to={`/jobs/${selected.id}?tab=executions`}>View job executions</Link>.</span>}
    </>}
    {failed && <span className="persona-job-feedback" role="alert">The run result could not be read. Check <Link className="text-link" to={selected ? `/jobs/${selected.id}?tab=executions` : '/jobs'}>job executions</Link> before trying again.</span>}
    {result && <span className="persona-job-feedback" role={personaOutcome(result.value).failed ? 'alert' : 'status'}>{personaOutcome(result.value).message}{' '}
      <Link className="text-link" to={`/jobs/${result.jobId}?tab=executions${result.value.execution_id ? `&execution=${result.value.execution_id}` : ''}`}>View execution{result.value.execution_id ? ` #${result.value.execution_id}` : 's'}</Link>
    </span>}
  </div>;
}
