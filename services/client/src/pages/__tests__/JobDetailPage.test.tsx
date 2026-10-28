import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, act } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { POLL_INTERVAL_MS } from '../../constants';
import { JobDetailPage } from '../JobDetailPage';

const mockNavigate = vi.fn();
const mockExecRefresh = vi.hoisted(() => vi.fn());
let mockParams: Record<string, string> = {};

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useParams: () => mockParams, useNavigate: () => mockNavigate };
});

vi.mock('../../hooks/usePagination', () => ({
  usePagination: vi.fn(() => ({
    items: [], total: 0, loading: false, limit: 10, offset: 0,
    setLimit: vi.fn(), setOffset: vi.fn(), setItems: vi.fn(), refresh: mockExecRefresh,
  })),
}));

vi.mock('../../api', () => ({
  api: {
    jobs: {
      get: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
      runNow: vi.fn(),
      executions: vi.fn(),
    },
  },
}));

import { api } from '../../api';

const mockGet = api.jobs.get as ReturnType<typeof vi.fn>;
const mockCreate = api.jobs.create as ReturnType<typeof vi.fn>;
const mockUpdate = api.jobs.update as ReturnType<typeof vi.fn>;
const mockRemove = api.jobs.remove as ReturnType<typeof vi.fn>;
const mockRunNow = api.jobs.runNow as ReturnType<typeof vi.fn>;

const fakeJob = {
  id: 42,
  name: 'Test Job',
  description: 'A test job',
  schedule_config: { minutes: 5 },
  input_params: { command: 'echo hi' },
  version: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
  configs: [{ id: 1, job_id: 42, device: '*', repo: '*', enabled: true, exclude: false, created_at: 'x', updated_at: 'x' }],
};

beforeEach(() => {
  vi.clearAllMocks();
  mockParams = { id: '42' };
  mockGet.mockResolvedValue(fakeJob);
  mockCreate.mockResolvedValue({ ...fakeJob, id: 99 });
  mockUpdate.mockResolvedValue(fakeJob);
  mockRemove.mockResolvedValue(undefined);
  mockRunNow.mockResolvedValue({ success: true, output: 'ok', error: '', duration_seconds: 0.1, exit_code: 0 });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('JobDetailPage', () => {
  describe('create mode', () => {
    beforeEach(() => { mockParams = { id: 'new' }; });

    it('starts in editing mode for new jobs', () => {
      renderWithProviders(<JobDetailPage />);
      expect(screen.getByPlaceholderText('Job name')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('echo hello')).toBeInTheDocument();
      expect(screen.getByText('Save')).toBeInTheDocument();
    });

    it('navigates back when cancel is clicked', () => {
      renderWithProviders(<JobDetailPage />);
      fireEvent.click(screen.getByText('Cancel'));
      expect(mockNavigate).toHaveBeenCalledWith('/jobs');
    });

    it('requires a command before saving', () => {
      renderWithProviders(<JobDetailPage />);
      fireEvent.change(screen.getByPlaceholderText('Job name'), { target: { value: 'My Job' } });
      fireEvent.click(screen.getByText('Save'));
      expect(mockCreate).not.toHaveBeenCalled();
    });

    it('creates and navigates on save', async () => {
      renderWithProviders(<JobDetailPage />);
      fireEvent.change(screen.getByPlaceholderText('Job name'), { target: { value: 'My Job' } });
      fireEvent.change(screen.getByPlaceholderText('echo hello'), { target: { value: 'echo done' } });
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(mockCreate).toHaveBeenCalledWith({
          name: 'My Job',
          schedule_config: { minutes: 5 },
          input_params: { command: 'echo done' },
          description: null,
        });
      });
      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/jobs/99', { replace: true });
      });
    });

    it('creates a graph schedule through the form on this device', async () => {
      renderWithProviders(<JobDetailPage />);
      fireEvent.change(screen.getByPlaceholderText('Job name'), { target: { value: 'Meetings: work' } });
      fireEvent.change(screen.getByLabelText('Job type'), { target: { value: 'graph' } });
      fireEvent.change(screen.getByLabelText('Graph'), { target: { value: 'meeting_ingest' } });
      fireEvent.change(screen.getByLabelText('Graph inputs (JSON)'), { target: { value: '{"source":"work"}' } });
      fireEvent.change(screen.getByLabelText('Run every'), { target: { value: '15' } });
      expect(screen.getByLabelText('Run on')).toHaveValue('this_device');
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => expect(mockCreate).toHaveBeenCalledWith({
        name: 'Meetings: work',
        schedule_config: { minutes: 15 },
        input_params: { graph_type: 'meeting_ingest', graph_inputs: { source: 'work' }, timeout: 300 },
        device_scope: 'this_device',
        description: null,
      }));
    });

    it.each(['{', '[]', 'null', '"text"', '1'])('rejects graph inputs that are not a JSON object: %s', (inputs) => {
      renderWithProviders(<JobDetailPage />);
      fireEvent.change(screen.getByPlaceholderText('Job name'), { target: { value: 'Meetings' } });
      fireEvent.change(screen.getByLabelText('Job type'), { target: { value: 'graph' } });
      fireEvent.change(screen.getByLabelText('Graph'), { target: { value: 'meeting_ingest' } });
      fireEvent.change(screen.getByLabelText('Graph inputs (JSON)'), { target: { value: inputs } });
      fireEvent.click(screen.getByText('Save'));
      expect(mockCreate).not.toHaveBeenCalled();
    });

    it('requires a graph name and a positive timeout', () => {
      renderWithProviders(<JobDetailPage />);
      fireEvent.change(screen.getByPlaceholderText('Job name'), { target: { value: 'Meetings' } });
      fireEvent.change(screen.getByLabelText('Job type'), { target: { value: 'graph' } });
      fireEvent.click(screen.getByText('Save'));
      expect(mockCreate).not.toHaveBeenCalled();
      fireEvent.change(screen.getByLabelText('Graph'), { target: { value: 'meeting_ingest' } });
      fireEvent.change(screen.getByLabelText('Timeout (seconds)'), { target: { value: '0' } });
      fireEvent.click(screen.getByText('Save'));
      expect(mockCreate).not.toHaveBeenCalled();
    });

    it('clears graph fields when switching back to a command', async () => {
      renderWithProviders(<JobDetailPage />);
      fireEvent.change(screen.getByPlaceholderText('Job name'), { target: { value: 'Command' } });
      fireEvent.change(screen.getByLabelText('Job type'), { target: { value: 'graph' } });
      fireEvent.change(screen.getByLabelText('Graph'), { target: { value: 'echo' } });
      fireEvent.change(screen.getByLabelText('Graph inputs (JSON)'), { target: { value: 'invalid abandoned input' } });
      fireEvent.change(screen.getByLabelText('Job type'), { target: { value: 'command' } });
      fireEvent.change(screen.getByPlaceholderText('echo hello'), { target: { value: 'echo hi' } });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => expect(mockCreate).toHaveBeenCalled());
      expect(mockCreate.mock.calls[0][0].input_params).toEqual({ command: 'echo hi', timeout: 300 });
    });

    it.each(['', '0'])('keeps a switched command timeout visible and validates it: %s', async (timeout) => {
      renderWithProviders(<JobDetailPage />);
      fireEvent.change(screen.getByPlaceholderText('Job name'), { target: { value: 'Command' } });
      fireEvent.change(screen.getByLabelText('Job type'), { target: { value: 'graph' } });
      fireEvent.change(screen.getByLabelText('Timeout (seconds)'), { target: { value: timeout } });
      fireEvent.change(screen.getByLabelText('Job type'), { target: { value: 'command' } });
      fireEvent.change(screen.getByPlaceholderText('echo hello'), { target: { value: 'echo hi' } });
      expect(screen.getByLabelText('Timeout (seconds)')).toBeVisible();
      fireEvent.click(screen.getByText('Save'));
      expect(mockCreate).not.toHaveBeenCalled();
      fireEvent.change(screen.getByLabelText('Timeout (seconds)'), { target: { value: '20' } });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => expect(mockCreate).toHaveBeenCalled());
      expect(mockCreate.mock.calls[0][0].input_params).toEqual({ command: 'echo hi', timeout: 20 });
    });

    it('keeps the graph draft after a server rejection and allows retry', async () => {
      mockCreate.mockRejectedValueOnce(new Error('Unknown graph'));
      renderWithProviders(<JobDetailPage />);
      fireEvent.change(screen.getByPlaceholderText('Job name'), { target: { value: 'Graph job' } });
      fireEvent.change(screen.getByLabelText('Job type'), { target: { value: 'graph' } });
      fireEvent.change(screen.getByLabelText('Graph'), { target: { value: 'wrong' } });
      fireEvent.change(screen.getByLabelText('Graph inputs (JSON)'), { target: { value: '{"text":"hello"}' } });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
      await waitFor(() => expect(screen.getByText('Save')).toBeEnabled());
      expect(mockNavigate).not.toHaveBeenCalled();
      expect(screen.getByLabelText('Graph inputs (JSON)')).toHaveValue('{"text":"hello"}');
      fireEvent.change(screen.getByLabelText('Graph'), { target: { value: 'echo' } });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/jobs/99', { replace: true }));
    });

    it('does not poll job data for new jobs', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      renderWithProviders(<JobDetailPage />);
      mockGet.mockClear();

      await act(async () => {
        vi.advanceTimersByTime(POLL_INTERVAL_MS);
        await Promise.resolve();
      });

      expect(mockGet).not.toHaveBeenCalled();
    });
  });

  describe('view mode', () => {
    it('displays and edits an existing graph without requiring a command', async () => {
      const params = { graph_type: 'meeting_ingest', graph_inputs: { source: 'work' }, timeout: 300 };
      mockGet.mockResolvedValue({ ...fakeJob, input_params: params });
      renderWithProviders(<JobDetailPage />);
      await waitFor(() => expect(screen.getByText('meeting_ingest')).toBeInTheDocument());
      expect(screen.getByText(/"source": "work"/)).toBeInTheDocument();
      expect(screen.queryByText('Command')).not.toBeInTheDocument();
      fireEvent.click(screen.getByText('Edit'));
      expect(screen.getByLabelText('Job type')).toHaveValue('graph');
      expect(screen.getByLabelText('Graph')).toHaveValue('meeting_ingest');
      fireEvent.change(screen.getByLabelText('Graph inputs (JSON)'), { target: { value: '{"source":"other"}' } });
      fireEvent.change(screen.getByLabelText('Timeout (seconds)'), { target: { value: '450' } });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith(42, {
        name: fakeJob.name,
        description: fakeJob.description,
        schedule_config: fakeJob.schedule_config,
        input_params: { ...params, graph_inputs: { source: 'other' }, timeout: 450 },
      }));
    });

    it('keeps edited graph inputs after an update failure and allows retry', async () => {
      mockGet.mockResolvedValue({ ...fakeJob, input_params: { graph_type: 'echo', graph_inputs: { text: 'old' }, timeout: 300 } });
      mockUpdate.mockRejectedValueOnce(new Error('Server unavailable'));
      renderWithProviders(<JobDetailPage />);
      await waitFor(() => expect(screen.getByText('Edit')).toBeInTheDocument());
      fireEvent.click(screen.getByText('Edit'));
      fireEvent.change(screen.getByLabelText('Graph inputs (JSON)'), { target: { value: '{"text":"new"}' } });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
      await waitFor(() => expect(screen.getByText('Save')).toBeEnabled());
      expect(screen.getByLabelText('Graph inputs (JSON)')).toHaveValue('{"text":"new"}');
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(2));
    });

    it('switches command jobs to graphs without submitting the old command', async () => {
      renderWithProviders(<JobDetailPage />);
      await waitFor(() => expect(screen.getByText('Edit')).toBeInTheDocument());
      fireEvent.click(screen.getByText('Edit'));
      fireEvent.change(screen.getByLabelText('Job type'), { target: { value: 'graph' } });
      fireEvent.change(screen.getByLabelText('Graph'), { target: { value: 'echo' } });
      fireEvent.change(screen.getByLabelText('Graph inputs (JSON)'), { target: { value: '{"text":"hello"}' } });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
      expect(mockUpdate.mock.calls[0][1].input_params).toEqual({
        graph_type: 'echo', graph_inputs: { text: 'hello' }, timeout: 300,
      });
    });

    it('loads and displays job data', async () => {
      renderWithProviders(<JobDetailPage />);
      await waitFor(() => expect(screen.getByText('Test Job')).toBeInTheDocument());
      expect(screen.getByText('Edit')).toBeInTheDocument();
      expect(screen.getByText('Delete')).toBeInTheDocument();
      expect(screen.getByText('Run Now')).toBeInTheDocument();
    });

    it('calls runNow on Run Now click', async () => {
      renderWithProviders(<JobDetailPage />);
      await waitFor(() => expect(screen.getByText('Run Now')).toBeInTheDocument());
      fireEvent.click(screen.getByText('Run Now'));
      await waitFor(() => expect(mockRunNow).toHaveBeenCalledWith(42));
    });

    it('polls job metadata every 60 seconds in view mode', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      renderWithProviders(<JobDetailPage />);

      await waitFor(() => expect(screen.getByText('Test Job')).toBeInTheDocument());
      mockGet.mockClear();

      await act(async () => {
        vi.advanceTimersByTime(POLL_INTERVAL_MS);
        await Promise.resolve();
      });

      expect(mockGet).toHaveBeenCalledWith(42);
    });

    it('does not poll job metadata while editing', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      renderWithProviders(<JobDetailPage />);

      await waitFor(() => expect(screen.getByText('Edit')).toBeInTheDocument());
      fireEvent.click(screen.getByText('Edit'));
      mockGet.mockClear();

      await act(async () => {
        vi.advanceTimersByTime(POLL_INTERVAL_MS);
        await Promise.resolve();
      });

      expect(mockGet).not.toHaveBeenCalled();
    });

    it('switches to the executions tab', async () => {
      renderWithProviders(<JobDetailPage />);
      await waitFor(() => expect(screen.getByText('Test Job')).toBeInTheDocument());
      fireEvent.click(screen.getByText('Executions'));
      expect(screen.getByText('No executions yet')).toBeInTheDocument();
    });

    it('polls executions only on the executions tab', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      renderWithProviders(<JobDetailPage />);

      await waitFor(() => expect(screen.getByText('Test Job')).toBeInTheDocument());
      mockExecRefresh.mockClear();

      await act(async () => {
        vi.advanceTimersByTime(POLL_INTERVAL_MS);
        await Promise.resolve();
      });
      expect(mockExecRefresh).not.toHaveBeenCalled();

      fireEvent.click(screen.getByText('Executions'));

      await act(async () => {
        vi.advanceTimersByTime(POLL_INTERVAL_MS);
        await Promise.resolve();
      });

      expect(mockExecRefresh).toHaveBeenCalledWith({ showLoading: false });
    });

    it('confirms before deleting', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
      renderWithProviders(<JobDetailPage />);
      await waitFor(() => expect(screen.getByText('Delete')).toBeInTheDocument());
      fireEvent.click(screen.getByText('Delete'));
      await waitFor(() => {
        expect(confirmSpy).toHaveBeenCalledWith('Delete job "Test Job"?');
        expect(mockRemove).toHaveBeenCalledWith(42);
      });
      confirmSpy.mockRestore();
    });
  });
});
