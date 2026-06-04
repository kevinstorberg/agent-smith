import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { JobDetailPage } from '../JobDetailPage';

const mockNavigate = vi.fn();
let mockParams: Record<string, string> = {};

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useParams: () => mockParams, useNavigate: () => mockNavigate };
});

vi.mock('../../hooks/usePagination', () => ({
  usePagination: vi.fn(() => ({
    items: [], total: 0, loading: false, limit: 10, offset: 0,
    setLimit: vi.fn(), setOffset: vi.fn(), setItems: vi.fn(),
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
  });

  describe('view mode', () => {
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

    it('switches to the executions tab', async () => {
      renderWithProviders(<JobDetailPage />);
      await waitFor(() => expect(screen.getByText('Test Job')).toBeInTheDocument());
      fireEvent.click(screen.getByText('Executions'));
      expect(screen.getByText('No executions yet')).toBeInTheDocument();
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
