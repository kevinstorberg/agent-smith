import { ScrollableTable } from '../components/ScrollableTable';
import './executionSorting.css';
import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router';
import { api } from '../api';
import type { Job, JobConfig, JobExecution } from '../api';
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
import { useApiRead } from '../hooks/useApiRead';
import { JobScheduleButton } from '../components/JobScheduleButton';
import { SortableHeader } from '../components/table/SortableHeader';
import { useLocalTableSort } from '../hooks/useLocalTableSort';
import type { LocalSortColumn } from '../utils/localTableSorting';
import './jobConfigSorting.css';

const EXECUTION_COLUMNS = {
  status: { ascending: 'status_asc', descending: 'status_desc' },
  started: {
    ascending: 'started_asc',
    descending: 'started_desc',
    defaultDirection: 'descending',
  },
  completed: {
    ascending: 'completed_asc',
    descending: 'completed_desc',
    defaultDirection: 'descending',
  },
  exit: { ascending: 'exit_asc', descending: 'exit_desc' },
} as const;

const INTERVAL_UNITS = ['seconds', 'minutes', 'hours', 'days'];
const CONFIG_SORT_COLUMNS = {
  device: {
    ascending: 'device_asc',
    descending: 'device_desc',
    select: (row: JobConfig) => row.device,
  },
  repo: {
    ascending: 'repo_asc',
    descending: 'repo_desc',
    select: (row: JobConfig) => row.repo,
  },
  enabled: {
    ascending: 'enabled_asc',
    descending: 'enabled_desc',
    select: (row: JobConfig) => row.enabled,
  },
  exclude: {
    ascending: 'exclude_asc',
    descending: 'exclude_desc',
    select: (row: JobConfig) => row.exclude,
  },
} as const satisfies Record<string, LocalSortColumn<JobConfig, string>>;

function scheduleParts(cfg: Record<string, number> | undefined): {
  value: number;
  unit: string;
} {
  const entries = Object.entries(cfg ?? {});
  if (entries.length) {
    const [unit, value] = entries[0];
    return { value: Number(value) || 1, unit };
  }
  return { value: 5, unit: 'minutes' };
}

function statusColor(status: string): string {
  return status === 'success'
    ? 'var(--success)'
    : status === 'running'
      ? 'var(--text-muted)'
      : '#e5534b';
}

export function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <JobDetail key={id || 'new'} id={id} />;
}

function JobDetail({ id }: { id?: string }) {
  const navigate = useNavigate();
  const { notify } = useNotification();
  const isNew = id === 'new' || !id;
  const [searchParams, setSearchParams] = useSearchParams();
  const personaPreset = isNew && searchParams.get('graph') === 'persona';
  const presetApplied = useRef(false);

  const [job, setJob] = useState<Job | null>(null);
  const configs = useLocalTableSort(
    job?.configs ?? [],
    CONFIG_SORT_COLUMNS,
    (row) => row.id,
  );
  const [loading, setLoading] = useState(!isNew);
  const [readError, setReadError] = useState(false);
  const mounted = useRef(false);
  const readVersion = useRef(0);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      readVersion.current += 1;
    };
  }, []);
  const tab =
    searchParams.get('tab') === 'executions' ? 'executions' : 'details';
  const setTab = (value: 'details' | 'executions') =>
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set('tab', value);
      return next;
    });
  const executionValue = Number(searchParams.get('execution'));
  const executionId =
    Number.isSafeInteger(executionValue) && executionValue > 0
      ? executionValue
      : null;
  const [execRefresh, setExecRefresh] = useState(0);
  const [graphInputsText, setGraphInputsText] = useState<string | null>(null);
  const [deviceScope, setDeviceScope] = useState<'all_devices' | 'this_device'>(
    'all_devices',
  );
  const [deviceScopeTouched, setDeviceScopeTouched] = useState(false);

  const {
    editing,
    saving,
    editValues,
    setEditValue,
    startEditing: startEdit,
    cancelEditing: cancelEdit,
    setSaving,
  } = useDetailPageEdit<Job>({
    initialData: job,
    isNew,
    onCancel: () => navigate('/jobs'),
  });
  useEffect(() => {
    if (personaPreset && !presetApplied.current) {
      presetApplied.current = true;
      setEditValue('name', 'Persona enrichment');
      setEditValue('input_params', {
        graph_type: 'persona',
        graph_inputs: {},
        timeout: 600,
      });
      setDeviceScope('all_devices');
    }
  }, [personaPreset, setEditValue]);

  const loadJob = useCallback(
    async ({ showLoading = true }: { showLoading?: boolean } = {}) => {
      if (isNew) return;
      const version = ++readVersion.current;
      if (showLoading) setLoading(true);
      try {
        const result = await api.jobs.get(Number(id));
        if (mounted.current && version === readVersion.current) {
          setJob(result);
          setReadError(false);
        }
      } catch {
        if (mounted.current && version === readVersion.current)
          setReadError(true);
      } finally {
        if (mounted.current && version === readVersion.current && showLoading)
          setLoading(false);
      }
    },
    [id, isNew],
  );
  const schedulingChanged = (updated: Job) => {
    if (!mounted.current || updated.id !== Number(id)) return;
    readVersion.current += 1;
    setJob((current) =>
      current?.id === updated.id
        ? {
            ...current,
            schedule_enabled: updated.schedule_enabled,
            version: updated.version,
            updated_at: updated.updated_at,
          }
        : current,
    );
    loadJob({ showLoading: false });
  };

  useEffect(() => {
    loadJob();
  }, [loadJob]);

  const createMutation = useApiMutation({
    mutationFn: api.jobs.create,
    onSuccess: (created) => navigate(`/jobs/${created.id}`, { replace: true }),
  });
  const updateMutation = useApiMutation({
    mutationFn: (data: Partial<Job>) => api.jobs.update(Number(id), data),
    onSuccess: async () => {
      await loadJob();
    },
  });
  const deleteMutation = useApiMutation({
    mutationFn: () => api.jobs.remove(Number(id)),
    onSuccess: () => navigate('/jobs'),
  });
  const runNowMutation = useApiMutation({
    mutationFn: () => api.jobs.runNow(Number(id)),
    onSuccess: (result) => {
      if (!mounted.current) return;
      notify(
        result.success
          ? 'Job ran successfully'
          : 'Job ran but reported failure',
        result.success ? 'success' : 'error',
      );
      setExecRefresh((n) => n + 1);
      setSearchParams((previous) => {
        const next = new URLSearchParams(previous);
        next.set('tab', 'executions');
        if (result.execution_id)
          next.set('execution', String(result.execution_id));
        else next.delete('execution');
        return next;
      });
    },
  });

  const [executionSort, setExecutionSort] = useState('started_desc');
  const exec = usePagination<JobExecution>(
    (l, o) =>
      isNew
        ? Promise.resolve({ items: [], total: 0 })
        : api.jobs.executions(Number(id), {
            limit: l,
            offset: o,
            ...(executionSort === 'started_desc'
              ? {}
              : { sort: executionSort }),
          }),
    [id, execRefresh, executionSort],
  );
  const readExecution = useCallback(
    () =>
      !isNew && executionId
        ? api.jobs.execution(Number(id), executionId)
        : Promise.resolve(null),
    [id, isNew, executionId],
  );
  const selectedExecution = useApiRead(readExecution);
  usePolling(() => selectedExecution.refresh({ showLoading: false }), {
    enabled:
      !isNew &&
      tab === 'executions' &&
      selectedExecution.data?.status === 'running',
  });
  usePolling(() => loadJob({ showLoading: false }), {
    enabled:
      !isNew &&
      !editing &&
      !saving &&
      !runNowMutation.loading &&
      !updateMutation.loading &&
      !deleteMutation.loading,
  });
  usePolling(() => exec.refresh({ showLoading: false }), {
    enabled:
      !isNew &&
      tab === 'executions' &&
      !editing &&
      !saving &&
      !runNowMutation.loading,
  });

  const inputParams = editValues.input_params ?? {};
  const jobType = 'graph_type' in inputParams ? 'graph' : 'command';
  const graphInputs =
    graphInputsText ?? JSON.stringify(inputParams.graph_inputs ?? {}, null, 2);

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
    if (isNew && !deviceScopeTouched)
      setDeviceScope(type === 'graph' ? 'this_device' : 'all_devices');
  };

  const changeGraph = (graph: string) => {
    const params: Record<string, unknown> = {
      ...inputParams,
      graph_type: graph,
    };
    const meetingGraph = ['meeting_ingest', 'persona'].includes(graph.trim());
    if (isNew && meetingGraph && Number(params.timeout ?? 300) < 600)
      params.timeout = 600;
    setEditValue('input_params', params);
    if (isNew && !deviceScopeTouched) {
      setDeviceScope(meetingGraph ? 'all_devices' : 'this_device');
    }
  };

  const save = async () => {
    const name = editValues.name ?? '';
    const nameErr = validators.compose(
      validators.required,
      validators.maxLength(MAX_TITLE_LENGTH),
    )(name);
    if (nameErr) {
      notify(
        nameErr === 'Required'
          ? 'Name is required.'
          : `Name must be ${MAX_TITLE_LENGTH} characters or fewer.`,
        'error',
      );
      return;
    }

    const input_params = { ...inputParams };
    if (jobType === 'graph') {
      const graph = String(input_params.graph_type ?? '').trim();
      if (!graph) {
        notify('Graph is required.', 'error');
        return;
      }
      let parsed: unknown;
      try {
        parsed = JSON.parse(graphInputs);
      } catch {
        notify('Graph inputs must be a JSON object.', 'error');
        return;
      }
      if (
        parsed === null ||
        typeof parsed !== 'object' ||
        Array.isArray(parsed)
      ) {
        notify('Graph inputs must be a JSON object.', 'error');
        return;
      }
      input_params.graph_type = graph;
      input_params.graph_inputs = parsed;
      delete input_params.command;
    } else {
      if (validators.required(input_params.command)) {
        notify('Command is required.', 'error');
        return;
      }
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
          name,
          schedule_config,
          input_params,
          description,
          ...(deviceScope === 'this_device'
            ? { device_scope: deviceScope }
            : {}),
        });
      } else {
        await updateMutation.mutate({
          name,
          schedule_config,
          input_params,
          description,
        });
      }
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="loading">Loading...</div>;
  if (!isNew && !job)
    return (
      <div className="loading">
        {readError ? 'Could not load job.' : 'Job not found'}
        {readError && (
          <button className="btn" onClick={() => loadJob()}>
            Retry
          </button>
        )}
      </div>
    );

  const sched = scheduleParts(editValues.schedule_config);
  const command = String(
    (editValues.input_params as Record<string, unknown> | undefined)?.command ??
      '',
  );

  return (
    <div>
      <DetailPageHeader
        backTo={{ label: 'jobs', path: '/jobs' }}
        editing={editing}
        saving={saving}
        onEdit={() => {
          setGraphInputsText(null);
          if (job) startEdit(job);
        }}
        onSave={save}
        onCancel={() => {
          setGraphInputsText(null);
          cancelEdit();
        }}
        onDelete={job ? () => deleteMutation.mutateAsync() : undefined}
        deleteConfirmMessage={job ? `Delete job "${job.name}"?` : undefined}
        showActions={!isNew || editing}
      />
      {readError && (
        <p role="alert">
          Could not refresh this job. Saved information is kept.{' '}
          <button
            className="btn btn-sm"
            onClick={() => loadJob({ showLoading: false })}
          >
            Retry
          </button>
        </p>
      )}

      {editing ? (
        <>
          <h2 className="page-title detail-form-title">
            {isNew ? 'New job' : 'Edit job'}
          </h2>
          <label className="form-label" htmlFor="job-name">
            Job name
          </label>
          <input
            id="job-name"
            className="input detail-title-input"
            value={editValues.name ?? ''}
            onChange={(e) => setEditValue('name', e.target.value)}
            placeholder="Job name"
            maxLength={MAX_TITLE_LENGTH}
          />
          <FieldError
            maxLength={MAX_TITLE_LENGTH}
            currentLength={editValues.name?.length ?? 0}
          />

          <label className="form-label detail-field-label" htmlFor="job-type">
            Job type
          </label>
          <select
            id="job-type"
            className="input"
            value={jobType}
            onChange={(e) => changeJobType(e.target.value)}
          >
            <option value="command">Command</option>
            <option value="graph">Graph</option>
          </select>

          {jobType === 'graph' ? (
            <>
              <label
                className="form-label detail-field-label"
                htmlFor="job-graph"
              >
                Graph
              </label>
              <input
                id="job-graph"
                className="input"
                style={{ width: '100%', fontFamily: 'var(--mono)' }}
                value={String(inputParams.graph_type ?? '')}
                onChange={(e) => changeGraph(e.target.value)}
                placeholder="meeting_ingest"
                list="meeting-graph-presets"
              />
              <datalist id="meeting-graph-presets">
                <option value="meeting_ingest">
                  Meeting transcripts and memories
                </option>
                <option value="persona">Persona enrichment</option>
              </datalist>
              <label
                className="form-label detail-field-label"
                htmlFor="job-graph-inputs"
              >
                Graph inputs (JSON)
              </label>
              <textarea
                id="job-graph-inputs"
                className="input"
                style={{
                  width: '100%',
                  minHeight: 100,
                  fontFamily: 'var(--mono)',
                }}
                value={graphInputs}
                onChange={(e) => setGraphInputsText(e.target.value)}
                placeholder="{}"
              />
              {String(inputParams.graph_type ?? '').trim() ===
                'meeting_ingest' && (
                <p className="text-muted-sm">
                  Use {'{}'} to import all configured meeting connections. Set
                  Timeout to 600 seconds for transcript and memory processing.
                </p>
              )}
              {String(inputParams.graph_type ?? '').trim() === 'persona' && (
                <p className="text-muted-sm">
                  Use {'{}'} to enrich profiles from all saved meeting
                  connections. Persona jobs use saved transcripts, run
                  independently of memory generation, and need a 600-second
                  timeout.
                </p>
              )}
            </>
          ) : (
            <>
              <label
                className="form-label detail-field-label"
                htmlFor="job-command"
              >
                Command
              </label>
              <input
                id="job-command"
                className="input"
                style={{ width: '100%', fontFamily: 'var(--mono)' }}
                value={command}
                onChange={(e) =>
                  setEditValue('input_params', {
                    ...inputParams,
                    command: e.target.value,
                  })
                }
                placeholder="echo hello"
              />
            </>
          )}

          {(jobType === 'graph' || 'timeout' in inputParams) && (
            <>
              <label
                className="form-label detail-field-label"
                htmlFor="job-timeout"
              >
                Timeout (seconds)
              </label>
              <input
                id="job-timeout"
                type="number"
                min={1}
                className="input"
                value={String(inputParams.timeout ?? 300)}
                onChange={(e) =>
                  setEditValue('input_params', {
                    ...inputParams,
                    timeout: e.target.value,
                  })
                }
              />
            </>
          )}

          <label
            className="form-label detail-field-label"
            htmlFor="job-interval"
          >
            Run every
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              id="job-interval"
              type="number"
              min={1}
              className="input"
              style={{ width: 100 }}
              value={sched.value}
              onChange={(e) =>
                setEditValue('schedule_config', {
                  [sched.unit]: Math.max(1, Number(e.target.value)),
                })
              }
            />
            <select
              aria-label="Interval unit"
              className="input"
              value={sched.unit}
              onChange={(e) =>
                setEditValue('schedule_config', {
                  [e.target.value]: sched.value,
                })
              }
            >
              {INTERVAL_UNITS.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </div>
          {Object.keys(editValues.schedule_config ?? {}).length > 1 && (
            <div
              style={{
                fontSize: 'var(--font-xs)',
                color: 'var(--text-muted)',
                marginTop: 4,
              }}
            >
              This job uses multiple time units; editing here collapses it to
              the single unit above.
            </div>
          )}

          {isNew && (
            <>
              <label
                className="form-label detail-field-label"
                htmlFor="job-device-scope"
              >
                Run on
              </label>
              <select
                id="job-device-scope"
                className="input"
                value={deviceScope}
                onChange={(e) => {
                  setDeviceScope(e.target.value as typeof deviceScope);
                  setDeviceScopeTouched(true);
                }}
              >
                <option value="this_device">This device</option>
                <option value="all_devices">All devices</option>
              </select>
              <p
                style={{
                  color: 'var(--text-muted)',
                  fontSize: 12,
                  marginTop: 6,
                }}
              >
                This device is the computer running the dashboard.
              </p>
            </>
          )}

          <label
            className="form-label detail-field-label"
            htmlFor="job-description"
          >
            Description
          </label>
          <textarea
            id="job-description"
            className="input"
            style={{ width: '100%', minHeight: 80 }}
            value={(editValues.description as string) ?? ''}
            onChange={(e) => setEditValue('description', e.target.value)}
            placeholder="Optional description"
          />
        </>
      ) : job ? (
        <>
          <h2 className="page-title" style={{ marginBottom: 8 }}>
            {job.name}
          </h2>
          <div className="job-run-controls">
            <span className="tag">{formatSchedule(job.schedule_config)}</span>
            {!job.schedule_enabled && (
              <span className="tag tag-warning">Paused</span>
            )}
            <div className="job-run-actions">
              <JobScheduleButton
                job={job}
                onChanged={schedulingChanged}
                disabled={
                  saving || updateMutation.loading || deleteMutation.loading
                }
              />
              <button
                className="btn btn-primary"
                onClick={() => runNowMutation.mutate()}
                disabled={runNowMutation.loading}
              >
                {runNowMutation.loading ? 'Running...' : 'Run Now'}
              </button>
            </div>
          </div>
          {!job.schedule_enabled && (
            <p className="text-muted-sm job-paused-notice">
              Automatic runs are paused. Run Now is still available; any active
              run will finish.
            </p>
          )}

          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <button
              className={`btn${tab === 'details' ? ' btn-primary' : ''}`}
              onClick={() => setTab('details')}
            >
              Details
            </button>
            <button
              className={`btn${tab === 'executions' ? ' btn-primary' : ''}`}
              onClick={() => setTab('executions')}
            >
              Executions
            </button>
          </div>

          {tab === 'details' && (
            <div className="card">
              {job.description && (
                <p style={{ marginBottom: 12 }}>{job.description}</p>
              )}
              {job.input_params.graph_type ? (
                <>
                  <label className="form-label detail-field-label">Graph</label>
                  <pre style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>
                    {String(job.input_params.graph_type)}
                  </pre>
                  <label className="form-label detail-field-label">
                    Graph inputs
                  </label>
                  <pre style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>
                    {JSON.stringify(
                      job.input_params.graph_inputs ?? {},
                      null,
                      2,
                    )}
                  </pre>
                  {job.input_params.timeout != null && (
                    <p>Timeout: {String(job.input_params.timeout)} seconds</p>
                  )}
                </>
              ) : (
                <>
                  <label className="form-label detail-field-label">
                    Command
                  </label>
                  <pre style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>
                    {String(job.input_params.command ?? '--')}
                  </pre>
                </>
              )}

              <label className="form-label detail-field-label">
                Configs (device / repo scoping)
              </label>
              <div
                className="job-config-table-region"
                role="region"
                aria-label="Job configuration list"
                tabIndex={0}
              >
                <table
                  className="table job-config-table"
                  aria-label="Job configurations"
                >
                  <thead>
                    <tr>
                      <SortableHeader
                        sort={configs.sort}
                        column={CONFIG_SORT_COLUMNS.device}
                        onSort={configs.setSort}
                      >
                        Device
                      </SortableHeader>
                      <SortableHeader
                        sort={configs.sort}
                        column={CONFIG_SORT_COLUMNS.repo}
                        onSort={configs.setSort}
                      >
                        Repo
                      </SortableHeader>
                      <SortableHeader
                        sort={configs.sort}
                        column={CONFIG_SORT_COLUMNS.enabled}
                        onSort={configs.setSort}
                      >
                        Enabled
                      </SortableHeader>
                      <SortableHeader
                        sort={configs.sort}
                        column={CONFIG_SORT_COLUMNS.exclude}
                        onSort={configs.setSort}
                      >
                        Exclude
                      </SortableHeader>
                    </tr>
                  </thead>
                  <tbody>
                    {configs.items.map((c) => (
                      <tr key={c.id}>
                        <td>{c.device}</td>
                        <td>{c.repo}</td>
                        <td>{c.enabled ? 'Yes' : 'No'}</td>
                        <td>{c.exclude ? 'Yes' : 'No'}</td>
                      </tr>
                    ))}
                    {(job.configs ?? []).length === 0 && (
                      <tr>
                        <td colSpan={4} className="loading">
                          No configs
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {tab === 'executions' && (
            <div>
              {executionId && (
                <section
                  className="card"
                  aria-label={`Execution ${executionId}`}
                >
                  <h3>Execution #{executionId}</h3>
                  {selectedExecution.loading ? (
                    <p>Loading execution...</p>
                  ) : selectedExecution.error ? (
                    <p role="alert">
                      Could not load this execution.{' '}
                      <button
                        className="btn btn-sm"
                        onClick={() => selectedExecution.refresh()}
                      >
                        Retry execution
                      </button>
                    </p>
                  ) : (
                    selectedExecution.data && (
                      <>
                        <p>Status: {selectedExecution.data.status}</p>
                        <pre
                          style={{
                            whiteSpace: 'pre-wrap',
                            overflowWrap: 'anywhere',
                          }}
                        >
                          {String(
                            selectedExecution.data.result.error ||
                              selectedExecution.data.result.output ||
                              'No output recorded.',
                          )}
                        </pre>
                      </>
                    )
                  )}
                </section>
              )}
              {exec.error && (
                <p role="alert">
                  Could not refresh executions.{' '}
                  <button className="btn btn-sm" onClick={() => exec.refresh()}>
                    Retry executions
                  </button>
                </p>
              )}
              {exec.initialLoading && (
                <p role="status">Loading executions...</p>
              )}
              <ScrollableTable
                label="Job executions"
                className="execution-sorting-table"
                busy={
                  (exec.loading || !exec.dataCurrent) &&
                  (exec.loading || !exec.error)
                }
                emptyState={
                  exec.dataCurrent &&
                  !exec.loading &&
                  !exec.error &&
                  exec.total === 0 ? (
                    <p className="loading">No executions yet</p>
                  ) : undefined
                }
              >
                <thead>
                  <tr>
                    <SortableHeader
                      sort={executionSort}
                      column={EXECUTION_COLUMNS.status}
                      onSort={setExecutionSort}
                      current={exec.dataCurrent && !exec.loading && !exec.error}
                    >
                      Status
                    </SortableHeader>
                    <SortableHeader
                      sort={executionSort}
                      column={EXECUTION_COLUMNS.started}
                      onSort={setExecutionSort}
                      current={exec.dataCurrent && !exec.loading && !exec.error}
                    >
                      Started
                    </SortableHeader>
                    <SortableHeader
                      sort={executionSort}
                      column={EXECUTION_COLUMNS.completed}
                      onSort={setExecutionSort}
                      current={exec.dataCurrent && !exec.loading && !exec.error}
                    >
                      Completed
                    </SortableHeader>
                    <SortableHeader
                      sort={executionSort}
                      column={EXECUTION_COLUMNS.exit}
                      onSort={setExecutionSort}
                      current={exec.dataCurrent && !exec.loading && !exec.error}
                    >
                      Exit
                    </SortableHeader>
                  </tr>
                </thead>
                <tbody>
                  {exec.items.map((e) => (
                    <tr key={e.id}>
                      <td>
                        <span
                          className="tag"
                          style={{ color: statusColor(e.status) }}
                        >
                          {e.status}
                        </span>
                      </td>
                      <td>
                        <DateCell date={e.started_at} />
                      </td>
                      <td>
                        {e.completed_at ? (
                          <DateCell date={e.completed_at} />
                        ) : (
                          '--'
                        )}
                      </td>
                      <td>{String(e.result?.exit_code ?? '--')}</td>
                    </tr>
                  ))}
                </tbody>
              </ScrollableTable>
              <Pagination
                total={exec.total}
                limit={exec.limit}
                offset={exec.offset}
                onPageChange={exec.setOffset}
                onLimitChange={(newLimit) => {
                  exec.setLimit(newLimit);
                  exec.setOffset(0);
                }}
              />
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
