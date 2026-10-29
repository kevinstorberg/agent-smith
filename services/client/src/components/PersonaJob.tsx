import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { GraphJob, JobRunResult } from '../api';
import { useApiRead } from '../hooks/useApiRead';
import { usePolling } from '../hooks/usePolling';
import { formatSchedule } from '../utils/schedule';
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

  return <section className="card" aria-label="Persona processing">
    <div className="page-header profiles-header"><h3 className="section-title">Persona processing</h3>
      <button className="btn" disabled={loading || Boolean(error) || !selected || running} onClick={run}>{running ? 'Running personas...' : 'Run personas'}</button>
    </div>
    {loading && !data ? <p className="text-muted-sm">Checking persona jobs...</p> : error ? <p role="alert">
      Could not check persona jobs. <button className="btn btn-sm" onClick={() => refresh()}>Retry job check</button>
    </p> : !selected ? <>
      <p>Automatic profile updates are not configured. Meeting imports and memories do not run persona reviews.</p>
      <p><Link className="text-link" to="/jobs/new?graph=persona">Create persona job</Link> to review saved transcripts on a schedule, or <Link className="text-link" to="/jobs">manage jobs</Link>.</p>
    </> : <>
      {jobs.length > 1 && <label className="form-label">Persona job <select className="input" aria-label="Persona job" value={selected.id} disabled={running}
        onChange={event => { setSelectedId(Number(event.target.value)); setResult(null); setFailed(false); }}>
        {jobs.map(job => <option key={job.id} value={job.id}>{job.name}</option>)}
      </select></label>}
      <p><Link className="text-link" to={`/jobs/${selected.id}`}>{selected.name}</Link> · {formatSchedule(selected.schedule_config)}{source(selected) ? ` · Connection: ${source(selected)}` : ' · All saved meeting connections'}</p>
      <p className="text-muted-sm">Reviews unreviewed transcripts and updates assessments from saved observations. Completed transcript reviews are kept.</p>
      {!selected.runs_on_device && <p className="text-muted-sm">This job does not run automatically on this device. You can run it here once or change its <Link className="text-link" to={`/jobs/${selected.id}`}>job settings</Link>.</p>}
      {running && <p role="status">Reviewing saved context. You can watch <Link className="text-link" to={`/jobs/${selected.id}?tab=executions`}>job executions</Link>.</p>}
    </>}
    {failed && <p role="alert">The run result could not be read. Check job executions before trying again.</p>}
    {result && <p role={personaOutcome(result.value).failed ? 'alert' : 'status'}>{personaOutcome(result.value).message}{' '}
      <Link className="text-link" to={`/jobs/${result.jobId}?tab=executions${result.value.execution_id ? `&execution=${result.value.execution_id}` : ''}`}>View execution{result.value.execution_id ? ` #${result.value.execution_id}` : 's'}</Link>
    </p>}
  </section>;
}
