import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { PersonaJob } from '../PersonaJob';
import type { GraphJob, JobRunResult } from '../../api';

vi.mock('../../api', () => ({ api: { jobs: { forGraph: vi.fn(), runNow: vi.fn() } } }));
import { api } from '../../api';

const job: GraphJob = { id: 42, name: 'Persona review', description: null, schedule_config: { minutes: 15 },
  input_params: { graph_type: 'persona', graph_inputs: {}, timeout: 600 }, version: 1,
  created_at: '', updated_at: '', runs_on_device: true, configs: [] };
const result = (outcome: string): JobRunResult => ({ execution_id: 77, success: true, error: '',
  output: JSON.stringify({ profiles: { outcome, profiles: 2 } }), duration_seconds: 1, exit_code: null });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.jobs.forGraph).mockResolvedValue({ items: [job], total: 1 });
  vi.mocked(api.jobs.runNow).mockResolvedValue(result('done'));
});

describe('PersonaJob', () => {
  it('reports applied assessments even when no new meeting was reviewed', async () => {
    vi.mocked(api.jobs.runNow).mockResolvedValue({ ...result('idle'), output: JSON.stringify({ profiles: { outcome: 'idle', profiles: 0 }, assessments: { outcome: 'done', profiles: 2 } }) });
    renderWithProviders(<PersonaJob onChanged={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run personas' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Run personas' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Updated 2 profile assessments. Changes are saved in History.'));
  });
  it('separates loading from missing configuration and offers explicit setup without creating a job', async () => {
    vi.mocked(api.jobs.forGraph).mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<PersonaJob onChanged={vi.fn()} />);
    expect(screen.getByText('Checking persona jobs...')).toBeInTheDocument();
    expect(await screen.findByText(/Automatic profile updates are not configured/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Create persona job' })).toHaveAttribute('href', '/jobs/new?graph=persona');
    expect(screen.getByRole('button', { name: 'Run personas' })).toBeDisabled();
    expect(api.jobs.runNow).not.toHaveBeenCalled();
  });

  it('does not mistake a failed status request for a missing job and supports retry', async () => {
    vi.mocked(api.jobs.forGraph).mockRejectedValueOnce(new Error('private status diagnostic'));
    renderWithProviders(<PersonaJob onChanged={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not check persona jobs.');
    expect(screen.queryByText(/not configured/)).not.toBeInTheDocument();
    expect(screen.queryByText('private status diagnostic')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry job check' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run personas' })).toBeEnabled());
  });

  it('prefers an eligible unrestricted job, prevents double clicks, and links its exact execution', async () => {
    vi.mocked(api.jobs.forGraph).mockResolvedValue({ items: [
      { ...job, id: 1, name: 'Scoped personas', input_params: { graph_type: 'persona', graph_inputs: { source: 'work' } } }, job,
    ], total: 2 });
    let complete!: (result: JobRunResult) => void;
    vi.mocked(api.jobs.runNow).mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
    const changed = vi.fn();
    renderWithProviders(<PersonaJob onChanged={changed} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run personas' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Run personas' }));
    fireEvent.click(screen.getByRole('button', { name: 'Running personas...' }));
    expect(api.jobs.runNow).toHaveBeenCalledTimes(1);
    expect(api.jobs.runNow).toHaveBeenCalledWith(42);
    expect(screen.getByRole('button', { name: 'Running personas...' })).toBeDisabled();
    await act(async () => complete(result('done')));
    expect(screen.getByRole('status')).toHaveTextContent('Reviewed one meeting and updated 2 profiles.');
    expect(screen.getByRole('link', { name: 'View execution #77' })).toHaveAttribute('href', '/jobs/42?tab=executions&execution=77');
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['continued', 'Progress saved. Run again or let scheduled runs continue'],
    ['idle', 'No unreviewed meeting transcripts or assessment updates are ready'],
  ])('reports %s without claiming all profiles are complete', async (value, message) => {
    vi.mocked(api.jobs.runNow).mockResolvedValue(result(value));
    renderWithProviders(<PersonaJob onChanged={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run personas' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Run personas' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(message));
  });

  it('shows a failed run with an execution link and keeps retry available', async () => {
    vi.mocked(api.jobs.runNow).mockResolvedValue({ ...result('failed'), success: false, error: 'Private diagnostic' });
    renderWithProviders(<PersonaJob onChanged={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run personas' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Run personas' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Persona update failed.');
    expect(screen.queryByText('Private diagnostic')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run personas' })).toBeEnabled();
  });

  it('reports an unreadable run result without claiming the request never started', async () => {
    vi.mocked(api.jobs.runNow).mockRejectedValueOnce(new Error('Private connection detail'));
    renderWithProviders(<PersonaJob onChanged={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run personas' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Run personas' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Check job executions before trying again.');
    expect(screen.queryByText('Private connection detail')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run personas' })).toBeEnabled();
  });

  it('labels scoped jobs not eligible on this device and permits an explicit one-time run', async () => {
    vi.mocked(api.jobs.forGraph).mockResolvedValue({ items: [{ ...job, runs_on_device: false,
      input_params: { graph_type: 'persona', graph_inputs: { source: 'work' } } }], total: 1 });
    renderWithProviders(<PersonaJob onChanged={vi.fn()} />);
    expect(await screen.findByText(/does not run automatically on this device/)).toBeInTheDocument();
    expect(screen.getByText(/Connection: work/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Run personas' }));
    await waitFor(() => expect(api.jobs.runNow).toHaveBeenCalledWith(42));
  });

  it('does not refresh the abandoned Profiles page after an in-flight run completes', async () => {
    let complete!: (result: JobRunResult) => void;
    vi.mocked(api.jobs.runNow).mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
    const changed = vi.fn();
    const { unmount } = renderWithProviders(<PersonaJob onChanged={changed} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run personas' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Run personas' }));
    unmount();
    await act(async () => complete(result('done')));
    expect(changed).not.toHaveBeenCalled();
  });
});
