import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { EvalDetailPage } from '../EvalDetailPage';

vi.mock('react-markdown', () => ({
  default: ({ children }: any) => <div data-testid="markdown">{children}</div>,
}));

vi.mock('remark-gfm', () => ({ default: {} }));

const mockNavigate = vi.fn();
let mockParams: Record<string, string> = {};

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return {
    ...actual,
    useParams: () => mockParams,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../../api', () => ({
  api: {
    evals: {
      get: vi.fn(),
      remove: vi.fn(),
    },
  },
}));

import { api } from '../../api';

const mockGet = api.evals.get as ReturnType<typeof vi.fn>;
const mockRemove = api.evals.remove as ReturnType<typeof vi.fn>;

const fakeRun = {
  id: 10,
  timestamp: '2026-03-01T10:00:00Z',
  eval_type: 'code',
  subcategory: 'quality',
  scenario: 'Test Scenario',
  test_model: 'claude-3',
  judge_model: 'claude-3-judge',
  threshold: 0.7,
  results: [
    { rule: 'Correctness', score: 0.9, reason: 'Output is correct' },
    { rule: 'Style', score: 0.5, reason: 'Style needs improvement' },
    { rule: 'Completeness', score: 0.8, reason: 'Mostly complete' },
  ],
  eval_suite_id: 1,
  created_at: '2026-03-01T10:00:00Z',
  prompt: 'Write a function',
  output: '# Agent output markdown',
};

beforeEach(() => {
  vi.clearAllMocks();
  mockParams = { id: '10' };
  mockGet.mockResolvedValue(fakeRun);
  mockRemove.mockResolvedValue({ deleted: 1 });
});

describe('EvalDetailPage', () => {
  it('shows loading state before data loads', () => {
    mockGet.mockReturnValue(new Promise(() => {}));

    renderWithProviders(<EvalDetailPage />);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('displays scenario name and metadata', async () => {
    renderWithProviders(<EvalDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Test Scenario')).toBeInTheDocument();
    });

    expect(screen.getByText('code / quality')).toBeInTheDocument();
    expect(screen.getByText('model: claude-3')).toBeInTheDocument();
    expect(screen.getByText('judge: claude-3-judge')).toBeInTheDocument();
    expect(screen.getByText('threshold: 0.7')).toBeInTheDocument();
  });

  it('calculates and displays average score correctly', async () => {
    renderWithProviders(<EvalDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Test Scenario')).toBeInTheDocument();
    });

    // Average of 0.9, 0.5, 0.8 = 0.7333...
    expect(screen.getByText('0.73')).toBeInTheDocument();
  });

  it('calculates pass and fail counts against threshold', async () => {
    renderWithProviders(<EvalDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Test Scenario')).toBeInTheDocument();
    });

    // Threshold is 0.7: Correctness (0.9) passes, Style (0.5) fails, Completeness (0.8) passes
    const passElement = screen.getByText('Passed').previousElementSibling;
    expect(passElement).toHaveTextContent('2');

    const failElement = screen.getByText('Failed').previousElementSibling;
    expect(failElement).toHaveTextContent('1');
  });

  it('displays individual result scores and reasons', async () => {
    renderWithProviders(<EvalDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Correctness')).toBeInTheDocument();
    });

    expect(screen.getByText('Style')).toBeInTheDocument();
    expect(screen.getByText('Completeness')).toBeInTheDocument();
    expect(screen.getByText('Output is correct')).toBeInTheDocument();
    expect(screen.getByText('Style needs improvement')).toBeInTheDocument();
  });

  it('switches to Agent Output tab', async () => {
    renderWithProviders(<EvalDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Test Scenario')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Agent Output'));

    expect(screen.getByTestId('markdown')).toHaveTextContent('# Agent output markdown');
  });

  it('switches to Raw JSON tab', async () => {
    renderWithProviders(<EvalDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Test Scenario')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Raw JSON'));

    const pre = screen.getByText(/"id": 10/);
    expect(pre).toBeInTheDocument();
  });

  it('switches back to Overview tab', async () => {
    renderWithProviders(<EvalDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Test Scenario')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Agent Output'));
    fireEvent.click(screen.getByText('Overview'));

    expect(screen.getByText('Results')).toBeInTheDocument();
    expect(screen.getByText('Correctness')).toBeInTheDocument();
  });

  it('confirms before deleting eval run', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderWithProviders(<EvalDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Delete')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Delete'));

    expect(confirmSpy).toHaveBeenCalledWith('Delete eval run #10?');
    expect(mockRemove).toHaveBeenCalledWith(10);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/evals');
    });

    confirmSpy.mockRestore();
  });

  it('does not delete when confirm is cancelled', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    renderWithProviders(<EvalDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Delete')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Delete'));

    expect(confirmSpy).toHaveBeenCalled();
    expect(mockRemove).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });

  it('navigates back to results on back link click', async () => {
    renderWithProviders(<EvalDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Test Scenario')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Back to Results/));

    expect(mockNavigate).toHaveBeenCalledWith('/evals');
  });

  it('navigates to eval config when suite link is clicked', async () => {
    renderWithProviders(<EvalDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Test Scenario')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/eval config/));

    expect(mockNavigate).toHaveBeenCalledWith('/eval-configs/1');
  });
});
