import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { EvalSuitesPage } from '../EvalSuitesPage';

const mockNavigate = vi.fn();

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../../api', () => ({
  api: {
    evalConfigs: {
      suites: {
        list: vi.fn(),
        update: vi.fn(),
      },
    },
  },
}));

import { api } from '../../api';

const mockList = api.evalConfigs.suites.list as ReturnType<typeof vi.fn>;
const mockSuiteUpdate = api.evalConfigs.suites.update as ReturnType<typeof vi.fn>;

const fakeSuites = [
  {
    id: 1,
    name: 'Code Quality Suite',
    eval_type: 'code',
    subcategory: 'quality',
    judge_prompt: '',
    items: {},
    config: {},
    enabled: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-15T10:00:00Z',
    scenario_count: 5,
  },
  {
    id: 2,
    name: 'Safety Suite',
    eval_type: 'safety',
    subcategory: 'toxicity',
    judge_prompt: '',
    items: {},
    config: {},
    enabled: false,
    created_at: '2026-02-01T00:00:00Z',
    updated_at: '2026-02-10T14:00:00Z',
    scenario_count: 3,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue({ items: fakeSuites, total: 2 });
  mockSuiteUpdate.mockResolvedValue({});
});

describe('EvalSuitesPage', () => {
  it('renders the suites table with data', async () => {
    renderWithProviders(<EvalSuitesPage />);

    await waitFor(() => {
      expect(screen.getByText('Code Quality Suite')).toBeInTheDocument();
    });

    expect(screen.getByText('Safety Suite')).toBeInTheDocument();
    expect(screen.getByText('code / quality')).toBeInTheDocument();
    expect(screen.getByText('safety / toxicity')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('2 suites')).toBeInTheDocument();
  });

  it('shows loading state initially', () => {
    mockList.mockReturnValue(new Promise(() => {}));

    renderWithProviders(<EvalSuitesPage />);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('shows empty state when no suites exist', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });

    renderWithProviders(<EvalSuitesPage />);

    await waitFor(() => {
      expect(screen.getByText('No eval suites found')).toBeInTheDocument();
    });

    expect(screen.getByText('0 suites')).toBeInTheDocument();
  });

  it('toggles enabled state on checkbox click', async () => {
    renderWithProviders(<EvalSuitesPage />);

    await waitFor(() => {
      expect(screen.getByText('Code Quality Suite')).toBeInTheDocument();
    });

    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[0]);

    await waitFor(() => {
      expect(mockSuiteUpdate).toHaveBeenCalledWith(1, { enabled: false });
    });
  });

  it('toggles disabled suite to enabled', async () => {
    renderWithProviders(<EvalSuitesPage />);

    await waitFor(() => {
      expect(screen.getByText('Safety Suite')).toBeInTheDocument();
    });

    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[1]);

    await waitFor(() => {
      expect(mockSuiteUpdate).toHaveBeenCalledWith(2, { enabled: true });
    });
  });

  it('navigates to suite detail on row click', async () => {
    renderWithProviders(<EvalSuitesPage />);

    await waitFor(() => {
      expect(screen.getByText('Code Quality Suite')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Code Quality Suite'));

    expect(mockNavigate).toHaveBeenCalledWith('/eval-configs/1');
  });

  it('navigates to new suite on button click', async () => {
    renderWithProviders(<EvalSuitesPage />);

    await waitFor(() => {
      expect(screen.getByText('+ New Suite')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('+ New Suite'));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/eval-configs/new');
    });
  });

  it('navigates to eval results on Results link click', async () => {
    renderWithProviders(<EvalSuitesPage />);

    await waitFor(() => {
      expect(screen.getByText('Code Quality Suite')).toBeInTheDocument();
    });

    const resultsLinks = screen.getAllByText(/Results/);
    fireEvent.click(resultsLinks[0]);

    expect(mockNavigate).toHaveBeenCalledWith('/evals?category=code&subcategory=quality');
  });
});
