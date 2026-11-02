import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Route, Routes, useLocation, useNavigate } from 'react-router';
import { renderWithProviders } from '../../test-utils';
import type { Job, JobRunResult } from '../../api';
import { POLL_INTERVAL_MS } from '../../constants';
import { JobsIndexPage } from '../JobsIndexPage';
import { JobDetailPage } from '../JobDetailPage';
import { jobFixture } from './jobFixture';

vi.mock('../../api', () => ({ api: { jobs: {
  list: vi.fn(), get: vi.fn(), setScheduling: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(),
  executions: vi.fn(), execution: vi.fn(), runNow: vi.fn(),
} } }));
import { api } from '../../api';
let jobs: Job[];
function Probe() {
  const navigate = useNavigate();
  const location = useLocation();
  return <><output data-testid="job-location">{location.pathname}{location.search}</output><button onClick={() => navigate('/jobs/43')}>Open other job</button></>;
}
function renderPage(path = '/jobs') {
  return renderWithProviders(<><Routes><Route path="/jobs" element={<JobsIndexPage />} />
    <Route path="/jobs/:id" element={<JobDetailPage />} /></Routes><Probe /></>, { initialEntries: [path] });
}
beforeEach(() => {
  vi.clearAllMocks();
  jobs = [structuredClone(jobFixture), { ...structuredClone(jobFixture), id: 43, name: 'Personas',
    input_params: { graph_type: 'persona', graph_inputs: {}, timeout: 600 } }];
  vi.mocked(api.jobs.list).mockImplementation(async () => ({ items: structuredClone(jobs), total: 2 }));
  vi.mocked(api.jobs.get).mockImplementation(async id => structuredClone(jobs.find(job => job.id === id)!));
  vi.mocked(api.jobs.setScheduling).mockImplementation(async (id, body) => {
    jobs = jobs.map(job => job.id === id ? { ...job, schedule_enabled: body.schedule_enabled, version: job.version + 1 } : job);
    return structuredClone(jobs.find(job => job.id === id)!);
  });
  vi.mocked(api.jobs.executions).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.jobs.execution).mockResolvedValue({ id: 77, job_id: 42, status: 'success', started_at: '', completed_at: '', result: { output: 'Synthetic manual run' } });
});
afterEach(() => vi.useRealTimers());

it('keeps the acknowledged one-job pause after a failed reread and ignores a pre-write list response', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  renderPage(); await screen.findByText('Meeting imports');
  let finishRead!: (value: { items: Job[]; total: number }) => void;
  const oldPage = structuredClone(jobs);
  vi.mocked(api.jobs.list).mockReturnValueOnce(new Promise(resolve => { finishRead = resolve; }));
  await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); });
  vi.mocked(api.jobs.list).mockRejectedValueOnce(new Error('Synthetic read failure'));
  fireEvent.click(screen.getByRole('button', { name: 'Pause automatic runs for Meeting imports' }));
  await screen.findByRole('button', { name: 'Resume automatic runs for Meeting imports' });
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not refresh jobs');
  await act(async () => finishRead({ items: oldPage, total: 2 }));
  expect(screen.getByRole('button', { name: 'Resume automatic runs for Meeting imports' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Pause automatic runs for Personas' })).toBeEnabled();
  expect(screen.getAllByRole('row')).toHaveLength(3);
  expect(api.jobs.setScheduling).toHaveBeenCalledExactlyOnceWith(42, { schedule_enabled: false });
  expect(jobs[0].configs).toEqual(jobFixture.configs); expect(jobs[1].schedule_enabled).toBe(true);
});

it('keeps the detail ACK after a stale read and allows scheduling changes during a manual run', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  renderPage('/jobs/42'); await screen.findByRole('heading', { name: 'Meeting imports' });
  let finishRead!: (value: Job) => void;
  const oldJob = structuredClone(jobs[0]);
  vi.mocked(api.jobs.get).mockReturnValueOnce(new Promise(resolve => { finishRead = resolve; }));
  await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); });
  vi.mocked(api.jobs.get).mockRejectedValueOnce(new Error('Synthetic read failure'));
  fireEvent.click(screen.getByRole('button', { name: 'Pause automatic runs for Meeting imports' }));
  await screen.findByText('Paused'); await screen.findByRole('alert');
  await act(async () => finishRead(oldJob));
  expect(screen.getByRole('button', { name: 'Resume automatic runs for Meeting imports' })).toBeEnabled();
  let finishRun!: (result: JobRunResult) => void;
  vi.mocked(api.jobs.runNow).mockReturnValueOnce(new Promise(resolve => { finishRun = resolve; }));
  fireEvent.click(screen.getByRole('button', { name: 'Run Now' }));
  expect(screen.getByRole('button', { name: 'Running...' })).toBeDisabled();
  const resume = screen.getByRole('button', { name: 'Resume automatic runs for Meeting imports' });
  expect(resume).toBeEnabled(); fireEvent.click(resume);
  await screen.findByRole('button', { name: 'Pause automatic runs for Meeting imports' });
  await act(async () => finishRun({ execution_id: 77, success: true, output: '', error: '', duration_seconds: 0, exit_code: 0 }));
  expect(api.jobs.runNow).toHaveBeenCalledExactlyOnceWith(42);
  expect(screen.getByRole('heading', { name: 'Meeting imports' })).toBeInTheDocument();
  expect(api.jobs.setScheduling).toHaveBeenLastCalledWith(42, { schedule_enabled: true });
});

it('never applies a pending job A acknowledgement to job B after navigation', async () => {
  renderPage('/jobs/42'); await screen.findByRole('heading', { name: 'Meeting imports' });
  let finish!: (job: Job) => void;
  vi.mocked(api.jobs.setScheduling).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  fireEvent.click(screen.getByRole('button', { name: 'Pause automatic runs for Meeting imports' }));
  fireEvent.click(screen.getByRole('button', { name: 'Open other job' }));
  await screen.findByRole('heading', { name: 'Personas' });
  const reads = vi.mocked(api.jobs.get).mock.calls.length;
  await act(async () => finish({ ...jobFixture, schedule_enabled: false }));
  expect(screen.getByRole('heading', { name: 'Personas' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Pause automatic runs for Personas' })).toBeEnabled();
  expect(screen.queryByText('Paused')).not.toBeInTheDocument();
  expect(api.jobs.get).toHaveBeenCalledTimes(reads);
  expect(api.jobs.setScheduling).toHaveBeenCalledExactlyOnceWith(42, { schedule_enabled: false });
});

it('does not leave job B when an earlier paused job A manual run completes', async () => {
  jobs[0].schedule_enabled = false;
  let finish!: (result: JobRunResult) => void;
  vi.mocked(api.jobs.runNow).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  renderPage('/jobs/42'); await screen.findByRole('heading', { name: 'Meeting imports' });
  fireEvent.click(screen.getByRole('button', { name: 'Run Now' }));
  fireEvent.click(screen.getByRole('button', { name: 'Open other job' }));
  await screen.findByRole('heading', { name: 'Personas' });
  await act(async () => finish({ execution_id: 77, success: true, output: '', error: '', duration_seconds: 0, exit_code: 0 }));
  await waitFor(() => expect(screen.getByTestId('job-location')).toHaveTextContent('/jobs/43'));
  expect(screen.getByTestId('job-location')).not.toHaveTextContent('execution=77');
  expect(screen.getByRole('heading', { name: 'Personas' })).toBeInTheDocument();
  expect(api.jobs.runNow).toHaveBeenCalledExactlyOnceWith(42);
});

it('ignores an old detail read after the route changes to another job', async () => {
  let finish!: (job: Job) => void;
  vi.mocked(api.jobs.get).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  renderPage('/jobs/42');
  fireEvent.click(screen.getByRole('button', { name: 'Open other job' }));
  await screen.findByRole('heading', { name: 'Personas' });
  await act(async () => finish(jobFixture));
  expect(screen.queryByRole('heading', { name: 'Meeting imports' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Pause automatic runs for Personas' })).toBeEnabled();
});

it('does not offer a scheduling mutation while editing the definition', async () => {
  jobs[0].schedule_enabled = false;
  renderPage('/jobs/42'); await screen.findByText('Paused');
  fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
  expect(screen.queryByRole('button', { name: /automatic runs for/ })).not.toBeInTheDocument();
  expect(api.jobs.setScheduling).not.toHaveBeenCalled();
});
