import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, act } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { EvalSuitesPage } from '../EvalSuitesPage';
import { defaultView, mergeViewCookie } from '../../utils/viewPreferences';

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
const mockSuiteUpdate = api.evalConfigs.suites.update as ReturnType<
  typeof vi.fn
>;

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
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.resetAllMocks();
  mockList.mockResolvedValue({ items: fakeSuites, total: 2 });
  mockSuiteUpdate.mockResolvedValue({});
});

describe('EvalSuitesPage', () => {
  afterEach(() => vi.useRealTimers());

  it('polls the current suite criteria and page silently at 15 seconds and stops after unmount', async () => {
    vi.useFakeTimers();
    document.cookie = mergeViewCookie('', 'evalSuites', {
      ...defaultView('evalSuites'),
      q: 'quality',
      enabled: 'true',
      sort: 'updated',
      limit: 25,
      offset: 50,
    });
    mockList.mockResolvedValue({ items: fakeSuites, total: 100 });
    let view!: ReturnType<typeof renderWithProviders>;
    await act(async () => {
      view = renderWithProviders(<EvalSuitesPage />);
    });
    const params = mockList.mock.calls.at(-1)![0];
    expect(params).toMatchObject({
      q: 'quality',
      enabled: 'true',
      limit: '25',
      offset: '50',
    });
    let finish!: (value: unknown) => void;
    mockList.mockClear().mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(14_999);
    });
    expect(mockList).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mockList).toHaveBeenCalledExactlyOnceWith(params);
    expect(screen.getByText('Code Quality Suite')).toBeVisible();
    expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    await act(async () => {
      finish({
        items: [{ ...fakeSuites[0], name: 'Updated suite' }],
        total: 100,
      });
    });
    expect(screen.getByText('Updated suite')).toBeVisible();
    view.unmount();
    mockList.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(mockList).not.toHaveBeenCalled();
  });

  it('pauses polling throughout a suite toggle and its canonical reread, then resumes', async () => {
    vi.useFakeTimers();
    await act(async () => {
      renderWithProviders(<EvalSuitesPage />);
    });
    let finishWrite!: (value: unknown) => void;
    let finishRead!: (value: unknown) => void;
    mockSuiteUpdate.mockReturnValueOnce(
      new Promise((resolve) => {
        finishWrite = resolve;
      }),
    );
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Enable Code Quality Suite' }),
    );
    mockList.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(mockList).not.toHaveBeenCalled();
    mockList.mockReturnValueOnce(
      new Promise((resolve) => {
        finishRead = resolve;
      }),
    );
    await act(async () => {
      finishWrite({});
    });
    expect(mockList).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(mockList).toHaveBeenCalledTimes(1);
    await act(async () => {
      finishRead({ items: fakeSuites, total: 2 });
    });
    mockList.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('resumes polling after a failed suite toggle without retrying the write', async () => {
    vi.useFakeTimers();
    await act(async () => {
      renderWithProviders(<EvalSuitesPage />);
    });
    mockSuiteUpdate.mockRejectedValueOnce(new Error('offline'));
    await act(async () => {
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Enable Code Quality Suite' }),
      );
    });
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Could not change the suite',
    );
    mockList.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(mockList).toHaveBeenCalledTimes(1);
    expect(mockSuiteUpdate).toHaveBeenCalledTimes(1);
  });
  it('renders the suites table with data', async () => {
    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });

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

    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('shows empty state when no suites exist', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });

    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });

    await waitFor(() => {
      expect(screen.getByText('No eval suites found')).toBeInTheDocument();
    });

    expect(screen.getByText('0 suites')).toBeInTheDocument();
  });

  it('toggles enabled state on checkbox click', async () => {
    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });

    await waitFor(() => {
      expect(screen.getByText('Code Quality Suite')).toBeInTheDocument();
    });

    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Enable Code Quality Suite' }),
    );

    await waitFor(() => {
      expect(mockSuiteUpdate).toHaveBeenCalledWith(1, { enabled: false });
    });
  });

  it('toggles disabled suite to enabled', async () => {
    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });

    await waitFor(() => {
      expect(screen.getByText('Safety Suite')).toBeInTheDocument();
    });

    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Enable Safety Suite' }),
    );

    await waitFor(() => {
      expect(mockSuiteUpdate).toHaveBeenCalledWith(2, { enabled: true });
    });
  });

  it('navigates to suite detail on row click', async () => {
    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });

    await waitFor(() => {
      expect(screen.getByText('Code Quality Suite')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Code Quality Suite'));

    expect(mockNavigate).toHaveBeenCalledWith('/eval-configs/1');
  });

  it('navigates to new suite on button click', async () => {
    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });

    await waitFor(() => {
      expect(screen.getByText('+ New Suite')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('+ New Suite'));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/eval-configs/new');
    });
  });

  it('links to eval results without activating suite row navigation', async () => {
    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });

    await waitFor(() => {
      expect(screen.getByText('Code Quality Suite')).toBeInTheDocument();
    });

    const resultsLinks = screen.getAllByRole('link', { name: 'Results →' });
    expect(resultsLinks[0]).toHaveAttribute(
      'href',
      '/evals?category=code&subcategory=quality',
    );
    fireEvent.click(resultsLinks[0]);

    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
