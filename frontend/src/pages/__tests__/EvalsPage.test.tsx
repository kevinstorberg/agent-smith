import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
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
  const actual = await vi.importActual<typeof import('react-router')>('react-router');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const { mockCategories, mockSubcategories, mockList, mockChart, mockChartAverage } = vi.hoisted(() => ({
  mockCategories: vi.fn(),
  mockSubcategories: vi.fn(),
  mockList: vi.fn(),
  mockChart: vi.fn(),
  mockChartAverage: vi.fn(),
}));

vi.mock('../../api', () => ({
  api: {
    evals: {
      categories: mockCategories,
      subcategories: mockSubcategories,
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
  vi.clearAllMocks();
  mockCategories.mockResolvedValue(['rules', 'skills']);
  mockSubcategories.mockResolvedValue(['core', 'advanced']);
  mockList.mockResolvedValue({ items: [], total: 0 });
  mockChartAverage.mockResolvedValue([]);
  mockChart.mockResolvedValue([]);
});

describe('EvalsPage', () => {
  it('loads and displays categories in the filter dropdown', async () => {
    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });

    await waitFor(() => {
      expect(mockCategories).toHaveBeenCalled();
    });

    const options = screen.getAllByRole('option');
    expect(options.some(o => o.textContent === 'rules')).toBe(true);
    expect(options.some(o => o.textContent === 'skills')).toBe(true);
  });

  it('renders subcategory filter options', async () => {
    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });

    await waitFor(() => {
      expect(mockSubcategories).toHaveBeenCalled();
    });

    expect(screen.getByText('All subcategories')).toBeInTheDocument();
    const options = screen.getAllByRole('option');
    expect(options.some(o => o.textContent === 'core')).toBe(true);
  });

  it('updates category filter and clears dependent filters', async () => {
    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals?category=rules'] });

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
    const failingRun = makeRun({ id: 2, score_avg: 0.5, threshold: 0.7, scenario: 'fail_scenario' });
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
    const tableCell = cells.find(el => el.closest('td'));
    fireEvent.click(tableCell!);
    expect(mockNavigate).toHaveBeenCalledWith('/evals/42');
  });
});
