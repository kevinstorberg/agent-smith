import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import { api } from '../api';
import type { Job, JobExecution } from '../api';
import { DetailPageHeader } from '../components/DetailPageHeader';
import { FieldError } from '../components/FieldError';
import { DateCell } from '../components/table';
import { Pagination } from '../components/Pagination';
import { useDetailPageEdit } from '../hooks/useDetailPageEdit';
import { useApiMutation } from '../hooks/useApiMutation';
import { usePagination } from '../hooks/usePagination';
import { usePolling } from '../hooks/usePolling';
import { useNotification } from '../context/useNotification';
import { MAX_TITLE_LENGTH } from '../constants';
import { validators } from '../utils/validation';
import { formatSchedule } from '../utils/schedule';

const INTERVAL_UNITS = ['seconds', 'minutes', 'hours', 'days'];

const styles = {
  input: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    color: 'var(--text)',
    padding: '8px 12px',
    fontSize: 18,
    fontWeight: 600,
    fontFamily: 'var(--font)',
    width: '100%',
  } as React.CSSProperties,
  label: {
    display: 'block',
    fontSize: 12,
    fontWeight: 500,
    color: 'var(--text-muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    margin: '16px 0 6px',
  } as React.CSSProperties,
  field: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    color: 'var(--text)',
    padding: '6px 10px',
    fontSize: 13,
    fontFamily: 'var(--font)',
  } as React.CSSProperties,
} as const;

function scheduleParts(cfg: Record<string, number> | undefined): { value: number; unit: string } {
  const entries = Object.entries(cfg ?? {});
  if (entries.length) {
    const [unit, value] = entries[0];
    return { value: Number(value) || 1, unit };
  }
  return { value: 5, unit: 'minutes' };
}

function statusColor(status: string): string {
  return status === 'success' ? 'var(--success)' : status === 'running' ? 'var(--text-muted)' : '#e5534b';
}

export function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { notify } = useNotification();
  const isNew = id === 'new' || !id;

  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(!isNew);
  const [tab, setTab] = useState<'details' | 'executions'>('details');
  const [execRefresh, setExecRefresh] = useState(0);
  const [graphInputsText, setGraphInputsText] = useState<string | null>(null);
  const [deviceScope, setDeviceScope] = useState<'all_devices' | 'this_device'>('all_devices');

  const {
    editing, saving, editValues, setEditValue,
    startEditing: startEdit, cancelEditing: cancelEdit, setSaving,
  } = useDetailPageEdit<Job>({ initialData: job, isNew, onCancel: () => navigate('/jobs') });

  const loadJob = useCallback(async ({ showLoading = true }: { showLoading?: boolean } = {}) => {
    if (isNew) return;
    if (showLoading) setLoading(true);
    try {
      setJob(await api.jobs.get(Number(id)));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [id, isNew]);

  useEffect(() => { loadJob(); }, [loadJob]);

  const createMutation = useApiMutation({
    mutationFn: api.jobs.create,
    onSuccess: (created) => navigate(`/jobs/${created.id}`, { replace: true }),
  });
  const updateMutation = useApiMutation({
    mutationFn: (data: Partial<Job>) => api.jobs.update(Number(id), data),
    onSuccess: async () => { await loadJob(); },
  });
  const deleteMutation = useApiMutation({
    mutationFn: () => api.jobs.remove(Number(id)),
    onSuccess: () => navigate('/jobs'),
  });
  const runNowMutation = useApiMutation({
    mutationFn: () => api.jobs.runNow(Number(id)),
    onSuccess: (result) => {
      notify(result.success ? 'Job ran successfully' : 'Job ran but reported failure', result.success ? 'success' : 'error');
      setExecRefresh(n => n + 1);
      setTab('executions');
    },
  });

  const exec = usePagination<JobExecution>(
    (l, o) => (isNew ? Promise.resolve({ items: [], total: 0 }) : api.jobs.executions(Number(id), { limit: l, offset: o })),
    [id, execRefresh],
  );
  usePolling(
    () => loadJob({ showLoading: false }),
    {
      enabled: !isNew && !editing && !saving && !runNowMutation.loading
        && !updateMutation.loading && !deleteMutation.loading,
    },
  );
  usePolling(
    () => exec.refresh({ showLoading: false }),
    { enabled: !isNew && tab === 'executions' && !editing && !saving && !runNowMutation.loading },
  );

  const inputParams = editValues.input_params ?? {};
  const jobType = 'graph_type' in inputParams ? 'graph' : 'command';
  const graphInputs = graphInputsText ?? JSON.stringify(inputParams.graph_inputs ?? {}, null, 2);

  const changeJobType = (type: string) => {
    const params = { ...inputParams };
    delete params.command;
    delete params.graph_type;
    delete params.graph_inputs;
    if (type === 'graph') {
      params.graph_type = '';
      params.graph_inputs = {};
      params.timeout ??= 300;
    } else {
      params.command = '';
    }
    setEditValue('input_params', params);
    setGraphInputsText(null);
    if (isNew) setDeviceScope(type === 'graph' ? 'this_device' : 'all_devices');
  };

  const save = async () => {
    const name = editValues.name ?? '';
    const nameErr = validators.compose(validators.required, validators.maxLength(MAX_TITLE_LENGTH))(name);
    if (nameErr) { notify(nameErr === 'Required' ? 'Name is required.' : `Name must be ${MAX_TITLE_LENGTH} characters or fewer.`, 'error'); return; }

    const input_params = { ...inputParams };
    if (jobType === 'graph') {
      const graph = String(input_params.graph_type ?? '').trim();
      if (!graph) { notify('Graph is required.', 'error'); return; }
      let parsed: unknown;
      try {
        parsed = JSON.parse(graphInputs);
      } catch {
        notify('Graph inputs must be a JSON object.', 'error');
        return;
      }
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        notify('Graph inputs must be a JSON object.', 'error');
        return;
      }
      input_params.graph_type = graph;
      input_params.graph_inputs = parsed;
      delete input_params.command;
    } else {
      if (validators.required(input_params.command)) { notify('Command is required.', 'error'); return; }
      delete input_params.graph_type;
      delete input_params.graph_inputs;
    }
    if (jobType === 'graph' || 'timeout' in input_params) {
      const timeout = Number(input_params.timeout ?? 300);
      if (!Number.isFinite(timeout) || timeout <= 0) {
        notify('Timeout must be a positive number of seconds.', 'error');
        return;
      }
      input_params.timeout = timeout;
    }

    const schedule_config = editValues.schedule_config ?? { minutes: 5 };
    const description = (editValues.description as string | null) || null;

    setSaving(true);
    try {
      if (isNew) {
        await createMutation.mutate({
          name, schedule_config, input_params, description,
          ...(deviceScope === 'this_device' ? { device_scope: deviceScope } : {}),
        });
      } else {
        await updateMutation.mutate({ name, schedule_config, input_params, description });
      }
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="loading">Loading...</div>;
  if (!isNew && !job) return <div className="loading">Job not found</div>;

  const sched = scheduleParts(editValues.schedule_config);
  const command = String((editValues.input_params as Record<string, unknown> | undefined)?.command ?? '');

  return (
    <div>
      <DetailPageHeader
        backTo={{ label: 'jobs', path: '/jobs' }}
        editing={editing}
        saving={saving}
        onEdit={() => { setGraphInputsText(null); if (job) startEdit(job); }}
        onSave={save}
        onCancel={() => { setGraphInputsText(null); cancelEdit(); }}
        onDelete={job ? () => deleteMutation.mutateAsync() : undefined}
        onNavigateBack={() => navigate('/jobs')}
        deleteConfirmMessage={job ? `Delete job "${job.name}"?` : undefined}
        showActions={!isNew || editing}
      />

      {editing ? (
        <>
          <input
            style={styles.input}
            value={editValues.name ?? ''}
            onChange={e => setEditValue('name', e.target.value)}
            placeholder="Job name"
            maxLength={MAX_TITLE_LENGTH}
          />
          <FieldError maxLength={MAX_TITLE_LENGTH} currentLength={editValues.name?.length ?? 0} />

          <label style={styles.label} htmlFor="job-type">Job type</label>
          <select id="job-type" style={styles.field} value={jobType} onChange={e => changeJobType(e.target.value)}>
            <option value="command">Command</option>
            <option value="graph">Graph</option>
          </select>

          {jobType === 'graph' ? (
            <>
              <label style={styles.label} htmlFor="job-graph">Graph</label>
              <input
                id="job-graph"
                style={{ ...styles.field, width: '100%', fontFamily: 'var(--mono)' }}
                value={String(inputParams.graph_type ?? '')}
                onChange={e => setEditValue('input_params', { ...inputParams, graph_type: e.target.value })}
                placeholder="meeting_ingest"
              />
              <label style={styles.label} htmlFor="job-graph-inputs">Graph inputs (JSON)</label>
              <textarea
                id="job-graph-inputs"
                style={{ ...styles.field, width: '100%', minHeight: 100, fontFamily: 'var(--mono)' }}
                value={graphInputs}
                onChange={e => setGraphInputsText(e.target.value)}
                placeholder={'{"source":"work"}'}
              />
            </>
          ) : (
            <>
              <label style={styles.label} htmlFor="job-command">Command</label>
              <input
                id="job-command"
                style={{ ...styles.field, width: '100%', fontFamily: 'var(--mono)' }}
                value={command}
                onChange={e => setEditValue('input_params', { ...inputParams, command: e.target.value })}
                placeholder="echo hello"
              />
            </>
          )}

          {(jobType === 'graph' || 'timeout' in inputParams) && (
            <>
              <label style={styles.label} htmlFor="job-timeout">Timeout (seconds)</label>
              <input
                id="job-timeout"
                type="number"
                min={1}
                style={styles.field}
                value={String(inputParams.timeout ?? 300)}
                onChange={e => setEditValue('input_params', { ...inputParams, timeout: e.target.value })}
              />
            </>
          )}

          <label style={styles.label} htmlFor="job-interval">Run every</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              id="job-interval"
              type="number"
              min={1}
              style={{ ...styles.field, width: 100 }}
              value={sched.value}
              onChange={e => setEditValue('schedule_config', { [sched.unit]: Math.max(1, Number(e.target.value)) })}
            />
            <select
              aria-label="Interval unit"
              style={styles.field}
              value={sched.unit}
              onChange={e => setEditValue('schedule_config', { [e.target.value]: sched.value })}
            >
              {INTERVAL_UNITS.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
          {Object.keys(editValues.schedule_config ?? {}).length > 1 && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
              This job uses multiple time units; editing here collapses it to the single unit above.
            </div>
          )}

          {isNew && (
            <>
              <label style={styles.label} htmlFor="job-device-scope">Run on</label>
              <select
                id="job-device-scope"
                style={styles.field}
                value={deviceScope}
                onChange={e => setDeviceScope(e.target.value as typeof deviceScope)}
              >
                <option value="this_device">This device</option>
                <option value="all_devices">All devices</option>
              </select>
              <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 6 }}>
                This device is the computer running the dashboard.
              </p>
            </>
          )}

          <label style={styles.label}>Description</label>
          <textarea
            style={{ ...styles.field, width: '100%', minHeight: 80 }}
            value={(editValues.description as string) ?? ''}
            onChange={e => setEditValue('description', e.target.value)}
            placeholder="Optional description"
          />
        </>
      ) : job ? (
        <>
          <h2 className="page-title" style={{ marginBottom: 8 }}>{job.name}</h2>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16 }}>
            <span className="tag">{formatSchedule(job.schedule_config)}</span>
            <button
              className="btn btn-primary"
              onClick={() => runNowMutation.mutateAsync()}
              disabled={runNowMutation.loading}
              style={{ marginLeft: 'auto' }}
            >
              {runNowMutation.loading ? 'Running...' : 'Run Now'}
            </button>
          </div>

          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <button className={`btn${tab === 'details' ? ' btn-primary' : ''}`} onClick={() => setTab('details')}>Details</button>
            <button className={`btn${tab === 'executions' ? ' btn-primary' : ''}`} onClick={() => setTab('executions')}>Executions</button>
          </div>

          {tab === 'details' && (
            <div className="card">
              {job.description && <p style={{ marginBottom: 12 }}>{job.description}</p>}
              {job.input_params.graph_type ? (
                <>
                  <label style={styles.label}>Graph</label>
                  <pre style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>{String(job.input_params.graph_type)}</pre>
                  <label style={styles.label}>Graph inputs</label>
                  <pre style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>{JSON.stringify(job.input_params.graph_inputs ?? {}, null, 2)}</pre>
                  {job.input_params.timeout != null && <p>Timeout: {String(job.input_params.timeout)} seconds</p>}
                </>
              ) : (
                <>
                  <label style={styles.label}>Command</label>
                  <pre style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>{String(job.input_params.command ?? '--')}</pre>
                </>
              )}

              <label style={styles.label}>Configs (device / repo scoping)</label>
              <table className="table">
                <thead><tr><th>Device</th><th>Repo</th><th>Enabled</th><th>Exclude</th></tr></thead>
                <tbody>
                  {(job.configs ?? []).map(c => (
                    <tr key={c.id}>
                      <td>{c.device}</td>
                      <td>{c.repo}</td>
                      <td>{c.enabled ? 'Yes' : 'No'}</td>
                      <td>{c.exclude ? 'Yes' : 'No'}</td>
                    </tr>
                  ))}
                  {(job.configs ?? []).length === 0 && (
                    <tr><td colSpan={4} className="loading">No configs</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {tab === 'executions' && (
            <div>
              <table className="table">
                <thead><tr><th>Status</th><th>Started</th><th>Completed</th><th>Exit</th></tr></thead>
                <tbody>
                  {exec.items.map(e => (
                    <tr key={e.id}>
                      <td><span className="tag" style={{ color: statusColor(e.status) }}>{e.status}</span></td>
                      <td><DateCell date={e.started_at} /></td>
                      <td>{e.completed_at ? <DateCell date={e.completed_at} /> : '--'}</td>
                      <td>{String(e.result?.exit_code ?? '--')}</td>
                    </tr>
                  ))}
                  {exec.items.length === 0 && (
                    <tr><td colSpan={4} className="loading">No executions yet</td></tr>
                  )}
                </tbody>
              </table>
              <Pagination
                total={exec.total}
                limit={exec.limit}
                offset={exec.offset}
                onPageChange={exec.setOffset}
                onLimitChange={newLimit => { exec.setLimit(newLimit); exec.setOffset(0); }}
              />
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
