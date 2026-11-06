import {
  defaultView,
  mergeViewCookie,
  readViewCookie,
} from '../../utils/viewPreferences';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, act } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { EvalsPage } from '../EvalsPage';

vi.mock('chart.js', () => ({
  Chart: { register: vi.fn() },
  CategoryScale: {},
  LinearScale: {},
  PointElement: {},
  LineElement: {},
  Title: {},
  Tooltip: {},
  Legend: {},
}));

vi.mock('react-chartjs-2', () => ({
  Line: () => <div data-testid="chart" />,
}));

const mockNavigate = vi.fn();
vi.mock('react-router', async () => {
  const actual =
    await vi.importActual<typeof import('react-router')>('react-router');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const {
  mockCategories,
  mockSubcategories,
  mockFacets,
  mockList,
  mockChart,
  mockChartAverage,
} = vi.hoisted(() => ({
  mockCategories: vi.fn(),
  mockSubcategories: vi.fn(),
  mockFacets: vi.fn(),
  mockList: vi.fn(),
  mockChart: vi.fn(),
  mockChartAverage: vi.fn(),
}));

vi.mock('../../api', () => ({
  api: {
    evals: {
      categories: mockCategories,
      subcategories: mockSubcategories,
      facets: mockFacets,
      list: mockList,
      chart: mockChart,
      chartAverage: mockChartAverage,
    },
  },
}));

function makeRun(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    timestamp: '2026-01-01T00:00:00Z',
    eval_type: 'rules',
    subcategory: 'core',
    scenario: 'test_scenario',
    test_model: 'gpt-4',
    judge_model: 'gpt-4',
    threshold: 0.7,
    score_avg: 0.85,
    score_count: 3,
    eval_suite_id: null,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.resetAllMocks();
  mockCategories.mockResolvedValue(['rules', 'skills']);
  mockSubcategories.mockResolvedValue(['core', 'advanced']);
  mockFacets.mockResolvedValue({
    scenarios: ['test_scenario'],
    models: ['gpt-4'],
  });
  mockList.mockResolvedValue({ items: [], total: 0 });
  mockChartAverage.mockResolvedValue([]);
  mockChart.mockResolvedValue([]);
});

describe('EvalsPage', () => {
  afterEach(() => vi.useRealTimers());

  it('waits for initial Results reads before starting a polling cycle', async () => {
    vi.useFakeTimers();
    let finish!: (value: string[]) => void;
    mockCategories.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    await act(async () => {
      renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    [
      mockList,
      mockChartAverage,
      mockCategories,
      mockSubcategories,
      mockFacets,
    ].forEach((read) => expect(read).toHaveBeenCalledTimes(1));
    await act(async () => {
      finish(['rules']);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    [
      mockList,
      mockChartAverage,
      mockCategories,
      mockSubcategories,
      mockFacets,
    ].forEach((read) => expect(read).toHaveBeenCalledTimes(2));
  });

  it('silently refreshes the current Results page, complete chart and filter options every 15 seconds', async () => {
    vi.useFakeTimers();
    document.cookie = mergeViewCookie('', 'results', {
      ...defaultView('results'),
      q: 'quality',
      category: 'skills',
      subcategory: 'core',
      scenario: 'test_scenario',
      model: 'gpt-4',
      sort: 'score',
      limit: 25,
      offset: 50,
    });
    mockList.mockResolvedValue({ items: [makeRun()], total: 100 });
    mockChartAverage.mockResolvedValue([
      { timestamp: '2026-01-01T00:00:00Z', score: 0.8 },
    ]);
    let view!: ReturnType<typeof renderWithProviders>;
    await act(async () => {
      view = renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });
    });
    const reads = [
      mockList,
      mockChartAverage,
      mockCategories,
      mockSubcategories,
      mockFacets,
    ];
    reads.forEach((read) => read.mockClear());
    let finish!: (value: unknown) => void;
    mockList.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    mockCategories.mockResolvedValue(['rules', 'skills', 'New category']);
    mockFacets.mockResolvedValue({
      scenarios: ['new scenario'],
      models: ['new model'],
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(14_999);
    });
    reads.forEach((read) => expect(read).not.toHaveBeenCalled());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    reads.forEach((read) => expect(read).toHaveBeenCalledTimes(1));
    expect(mockList).toHaveBeenLastCalledWith({
      eval_type: 'skills',
      subcategory: 'core',
      scenario: 'test_scenario',
      model: 'gpt-4',
      q: 'quality',
      sort: 'score',
      limit: '25',
      offset: '50',
    });
    expect(mockChartAverage).toHaveBeenLastCalledWith({
      eval_type: 'skills',
      subcategory: 'core',
      scenario: 'test_scenario',
      model: 'gpt-4',
      q: 'quality',
    });
    expect(mockFacets).toHaveBeenLastCalledWith({
      eval_type: 'skills',
      subcategory: 'core',
      q: 'quality',
    });
    expect(
      screen.getByRole('option', { name: 'New category' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('option', { name: 'new scenario' }),
    ).toBeInTheDocument();
    expect(screen.getByTestId('chart')).toBeVisible();
    expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    expect(screen.queryByText('Loading chart...')).not.toBeInTheDocument();
    await act(async () => {
      finish({
        items: [makeRun({ scenario: 'New agent result' })],
        total: 100,
      });
    });
    expect(screen.getByText('New agent result')).toBeVisible();
    view.unmount();
    reads.forEach((read) => read.mockClear());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    reads.forEach((read) => expect(read).not.toHaveBeenCalled());
  });

  it.each(['list', 'chart', 'categories', 'subcategories', 'facets'] as const)(
    'waits for the %s request before another grouped Results poll',
    async (held) => {
      vi.useFakeTimers();
      await act(async () => {
        renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });
      });
      const reads = {
        list: mockList,
        chart: mockChartAverage,
        categories: mockCategories,
        subcategories: mockSubcategories,
        facets: mockFacets,
      };
      Object.values(reads).forEach((read) => read.mockClear());
      let finish!: (value: unknown) => void;
      reads[held].mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve;
        }),
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      Object.values(reads).forEach((read) =>
        expect(read).toHaveBeenCalledTimes(1),
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      Object.values(reads).forEach((read) =>
        expect(read).toHaveBeenCalledTimes(1),
      );
      const value =
        held === 'list'
          ? { items: [], total: 0 }
          : held === 'facets'
            ? { scenarios: [], models: [] }
            : [];
      await act(async () => {
        finish(value);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      Object.values(reads).forEach((read) =>
        expect(read).toHaveBeenCalledTimes(2),
      );
    },
  );

  it('keeps a later Results query when a prior poll completes last', async () => {
    vi.useFakeTimers();
    await act(async () => {
      renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });
    });
    let finish!: (value: unknown) => void;
    mockList.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    mockList.mockResolvedValue({
      items: [makeRun({ scenario: 'current result' })],
      total: 1,
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'current' },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(screen.getByText('current result')).toBeVisible();
    await act(async () => {
      finish({ items: [makeRun({ scenario: 'stale result' })], total: 1 });
    });
    expect(screen.queryByText('stale result')).not.toBeInTheDocument();
    expect(mockChartAverage).toHaveBeenLastCalledWith({ q: 'current' });
  });
  it('restores the same filters before table, facet and chart reads and atomically clears dependent criteria', async () => {
    document.cookie = mergeViewCookie('', 'results', {
      ...defaultView('results'),
      q: 'quality',
      category: 'skills',
      subcategory: 'core',
      scenario: 'test_scenario',
      model: 'gpt-4',
      sort: 'score',
      limit: 25,
      offset: 50,
    });
    mockList.mockResolvedValue({ items: [], total: 100 });
    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals?keep=1'] });
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    expect(mockList).toHaveBeenCalledWith({
      eval_type: 'skills',
      subcategory: 'core',
      scenario: 'test_scenario',
      model: 'gpt-4',
      q: 'quality',
      sort: 'score',
      limit: '25',
      offset: '50',
    });
    expect(mockChartAverage).toHaveBeenCalledWith({
      eval_type: 'skills',
      subcategory: 'core',
      scenario: 'test_scenario',
      model: 'gpt-4',
      q: 'quality',
    });
    expect(mockFacets).toHaveBeenCalledWith({
      eval_type: 'skills',
      subcategory: 'core',
      q: 'quality',
    });
    mockList.mockClear();
    fireEvent.change(screen.getByLabelText('Result category'), {
      target: { value: '' },
    });
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    expect(mockList).toHaveBeenCalledWith({
      q: 'quality',
      sort: 'score',
      limit: '25',
      offset: '0',
    });
    expect(readViewCookie(document.cookie)[0].values).toEqual({
      q: 'quality',
      sort: 'score',
      limit: 25,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Time' }));
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({
        q: 'quality',
        sort: 'newest',
        limit: '25',
        offset: '0',
      }),
    );
    expect(readViewCookie(document.cookie)).toEqual([
      { key: 'results', values: { q: 'quality', limit: 25 } },
    ]);
  });

  it('requests all result categories by default across the table, facets and chart', async () => {
    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    expect(screen.getByLabelText('Result category')).toHaveValue('');
    expect(mockList).toHaveBeenCalledWith({
      sort: 'newest',
      limit: '10',
      offset: '0',
    });
    expect(mockSubcategories).toHaveBeenCalledWith({});
    expect(mockFacets).toHaveBeenCalledWith({});
    expect(mockChartAverage).toHaveBeenCalledWith({});
  });

  it('can return from an explicit category to all categories and clear dependent filters', async () => {
    renderWithProviders(<EvalsPage />, {
      initialEntries: [
        '/evals?category=rules&subcategory=core&scenario=test_scenario&model=gpt-4&q=check',
      ],
    });
    await waitFor(() =>
      expect(mockList).toHaveBeenCalledWith(
        expect.objectContaining({ eval_type: 'rules', q: 'check' }),
      ),
    );
    fireEvent.change(screen.getByLabelText('Result category'), {
      target: { value: '' },
    });
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({
        q: 'check',
        sort: 'newest',
        limit: '10',
        offset: '0',
      }),
    );
    expect(screen.getByLabelText('Result subcategory')).toHaveValue('');
    expect(screen.getByLabelText('Result scenario')).toHaveValue('');
    expect(screen.getByLabelText('Result model')).toHaveValue('');
    expect(mockChartAverage).toHaveBeenLastCalledWith({ q: 'check' });
  });

  it('loads and displays categories in the filter dropdown', async () => {
    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });

    await waitFor(() => {
      expect(mockCategories).toHaveBeenCalled();
    });

    const options = screen.getAllByRole('option');
    expect(options.some((o) => o.textContent === 'rules')).toBe(true);
    expect(options.some((o) => o.textContent === 'skills')).toBe(true);
  });

  it('renders subcategory filter options', async () => {
    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });

    await waitFor(() => {
      expect(mockSubcategories).toHaveBeenCalled();
    });

    expect(screen.getByText('All subcategories')).toBeInTheDocument();
    const options = screen.getAllByRole('option');
    expect(options.some((o) => o.textContent === 'core')).toBe(true);
  });

  it('updates category filter and clears dependent filters', async () => {
    renderWithProviders(<EvalsPage />, {
      initialEntries: ['/evals?category=rules'],
    });

    await waitFor(() => {
      expect(mockCategories).toHaveBeenCalled();
    });

    const categorySelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(categorySelect, { target: { value: 'skills' } });

    await waitFor(() => {
      expect(mockSubcategories).toHaveBeenCalledWith(
        expect.objectContaining({ eval_type: 'skills' }),
      );
    });
  });

  it('shows chart mode toggle and switches between average and breakdown', async () => {
    const runs = [makeRun({ score_count: 3 })];
    mockList.mockResolvedValue({ items: runs, total: 1 });

    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    const avgButton = screen.getByRole('button', { name: 'Average' });
    expect(avgButton.className).toContain('active');

    const breakdownButton = screen.getByRole('button', { name: 'Breakdown' });
    fireEvent.click(breakdownButton);

    await waitFor(() => {
      expect(mockChart).toHaveBeenCalled();
    });
  });

  it('renders score badge with pass/fail class', async () => {
    const passingRun = makeRun({ id: 1, score_avg: 0.85, threshold: 0.7 });
    const failingRun = makeRun({
      id: 2,
      score_avg: 0.5,
      threshold: 0.7,
      scenario: 'fail_scenario',
    });
    mockList.mockResolvedValue({ items: [passingRun, failingRun], total: 2 });

    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    const badges = document.querySelectorAll('.score-badge');
    expect(badges).toHaveLength(2);
    expect(badges[0].className).toContain('pass');
    expect(badges[1].className).toContain('fail');
  });

  it('renders a table with eval run data', async () => {
    const runs = [makeRun()];
    mockList.mockResolvedValue({ items: runs, total: 1 });

    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    // scenario and model appear in both the table and the filter dropdowns
    const scenarioCells = screen.getAllByText('test_scenario');
    expect(scenarioCells.length).toBeGreaterThanOrEqual(1);
    const modelCells = screen.getAllByText('gpt-4');
    expect(modelCells.length).toBeGreaterThanOrEqual(1);
  });

  it('shows empty state when no runs found', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });

    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    expect(screen.getByText('No eval runs found')).toBeInTheDocument();
  });

  it('navigates to eval detail on row click', async () => {
    const runs = [makeRun({ id: 42 })];
    mockList.mockResolvedValue({ items: runs, total: 1 });

    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    // Click the table cell (not the select option)
    const cells = screen.getAllByText('test_scenario');
    const tableCell = cells.find((el) => el.closest('td'));
    fireEvent.click(tableCell!);
    expect(mockNavigate).toHaveBeenCalledWith('/evals/42');
  });
});
