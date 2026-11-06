import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../api';
import type { EvalRun, Paginated } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { EvalsPage } from '../EvalsPage';
import { resultSortingRows } from './resultSortingFixture';

vi.mock('../../components/ScoreChart', () => ({ ScoreChart: () => null }));
vi.mock('../../api', () => ({
  api: {
    evals: {
      list: vi.fn(),
      categories: vi.fn(),
      subcategories: vi.fn(),
      facets: vi.fn(),
      chart: vi.fn(),
      chartAverage: vi.fn(),
    },
  },
}));
const response = (scenario: string): Paginated<EvalRun> => ({
  items: [{ ...resultSortingRows[0], scenario }],
  total: 30,
});
const header = (name: string) => screen.getByRole('columnheader', { name });
const button = (name: string) => within(header(name)).getByRole('button');
beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.resetAllMocks();
  vi.mocked(api.evals.categories).mockResolvedValue(['rules']);
  vi.mocked(api.evals.subcategories).mockResolvedValue(['core']);
  vi.mocked(api.evals.facets).mockResolvedValue({ scenarios: [], models: [] });
  vi.mocked(api.evals.chartAverage).mockResolvedValue([]);
  vi.mocked(api.evals.chart).mockResolvedValue([]);
  vi.mocked(api.evals.list).mockResolvedValue(response('Accepted row'));
});

describe('Results header sorting', () => {
  it.each([
    ['Time', 'newest', 'oldest'],
    ['Category', 'category_asc', 'category_desc'],
    ['Scenario', 'scenario_asc', 'scenario_desc'],
    ['Model', 'model_asc', 'model_desc'],
    ['Threshold', 'threshold_asc', 'threshold_desc'],
    ['Scores', 'score', 'score_asc'],
  ])(
    'toggles %s in both server directions and preserves chart reads',
    async (label, first, second) => {
      renderWithProviders(<EvalsPage />, {
        initialEntries: ['/evals?sort=category_desc'],
      });
      await screen.findByText('Accepted row');
      expect(
        screen.queryByRole('combobox', { name: 'Sort results' }),
      ).not.toBeInTheDocument();
      const chartReads = vi.mocked(api.evals.chartAverage).mock.calls.length;
      for (const sort of [first, second]) {
        fireEvent.click(button(label));
        await waitFor(() =>
          expect(api.evals.list).toHaveBeenLastCalledWith(
            expect.objectContaining({ sort, offset: '0' }),
          ),
        );
        await waitFor(() =>
          expect(header(label)).toHaveAttribute(
            'aria-sort',
            sort.endsWith('_asc') || sort === 'oldest'
              ? 'ascending'
              : 'descending',
          ),
        );
      }
      expect(api.evals.chartAverage).toHaveBeenCalledTimes(chartReads);
    },
  );

  it('resets an accepted second page while preserving all filters and complete chart context', async () => {
    vi.mocked(api.evals.list).mockImplementation(async (params) =>
      response(
        params?.sort === 'scenario_asc'
          ? 'Aardvark outside old page'
          : 'Committed page two',
      ),
    );
    renderWithProviders(<EvalsPage />, {
      initialEntries: [
        '/evals?category=rules&subcategory=core&model=offline&scenario=check&q=release&limit=25&offset=25',
      ],
    });
    await screen.findByText('Committed page two');
    expect(screen.getByText('Showing 26–30 of 30')).toBeInTheDocument();
    vi.mocked(api.evals.list).mockClear();
    fireEvent.click(button('Scenario'));
    await screen.findByText('Aardvark outside old page');
    expect(api.evals.list).toHaveBeenCalledExactlyOnceWith({
      eval_type: 'rules',
      subcategory: 'core',
      model: 'offline',
      scenario: 'check',
      q: 'release',
      sort: 'scenario_asc',
      limit: '25',
      offset: '0',
    });
    expect(api.evals.chartAverage).toHaveBeenLastCalledWith({
      eval_type: 'rules',
      subcategory: 'core',
      model: 'offline',
      scenario: 'check',
      q: 'release',
    });
  });

  it('retains native focus during pending orders and rejects a late ascending result', async () => {
    let ascend!: (value: Paginated<EvalRun>) => void;
    let descend!: (value: Paginated<EvalRun>) => void;
    const ascending = new Promise<Paginated<EvalRun>>((resolve) => {
      ascend = resolve;
    });
    const descending = new Promise<Paginated<EvalRun>>((resolve) => {
      descend = resolve;
    });
    vi.mocked(api.evals.list).mockImplementation((params) =>
      params?.sort === 'scenario_asc'
        ? ascending
        : params?.sort === 'scenario_desc'
          ? descending
          : Promise.resolve(response('Initial row')),
    );
    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });
    await screen.findByText('Initial row');
    const target = button('Scenario');
    target.focus();
    const user = userEvent.setup();
    await user.keyboard('{Enter}');
    await waitFor(() =>
      expect(api.evals.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'scenario_asc' }),
      ),
    );
    expect(target).toHaveFocus();
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    expect(document.querySelector('[aria-sort]')).toBeNull();
    await user.keyboard(' ');
    await waitFor(() =>
      expect(api.evals.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'scenario_desc' }),
      ),
    );
    await act(async () => descend(response('Current descending row')));
    await screen.findByText('Current descending row');
    await act(async () => ascend(response('Obsolete ascending row')));
    expect(
      screen.queryByText('Obsolete ascending row'),
    ).not.toBeInTheDocument();
    expect(header('Scenario')).toHaveAttribute('aria-sort', 'descending');
    expect(target).toHaveFocus();
  });

  it('keeps headers operable for no matches and clears busy after a failed new order', async () => {
    vi.mocked(api.evals.list).mockResolvedValueOnce({ items: [], total: 0 });
    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });
    await screen.findByText('No eval runs found');
    expect(screen.getByRole('table')).not.toHaveClass('table-empty');
    const target = button('Scenario');
    target.focus();
    vi.mocked(api.evals.list).mockRejectedValueOnce(
      new Error('Order unavailable'),
    );
    fireEvent.click(target);
    await screen.findByRole('alert');
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'false');
    expect(document.querySelector('[aria-sort]')).toBeNull();
    expect(target).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('Accepted row');
    expect(header('Scenario')).toHaveAttribute('aria-sort', 'ascending');
  });
});
