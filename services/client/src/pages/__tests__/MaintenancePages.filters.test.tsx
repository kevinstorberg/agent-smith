import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { api } from '../../api';
import type {
  AverageChartPoint,
  EvalRun,
  Paginated,
  Proposal,
} from '../../api';
import { AuditIndexPage } from '../AuditIndexPage';
import { EvalSuitesPage } from '../EvalSuitesPage';
import { ProposalsIndexPage } from '../ProposalsIndexPage';
import { EvalsPage } from '../EvalsPage';

const maintenanceRoutes: Record<string, string> = {
  audit: '/audit',
  suites: '/eval-configs',
  proposals: '/proposals',
  results: '/evals',
};

vi.mock('../../api', () => ({
  api: {
    audit: { list: vi.fn(), counts: vi.fn() },
    evalConfigs: { suites: { list: vi.fn(), update: vi.fn() } },
    proposals: {
      list: vi.fn(),
      counts: vi.fn(),
      approve: vi.fn(),
      reject: vi.fn(),
      generate: vi.fn(),
    },
    evals: {
      categories: vi.fn(),
      subcategories: vi.fn(),
      facets: vi.fn(),
      list: vi.fn(),
      chart: vi.fn(),
      chartAverage: vi.fn(),
    },
  },
}));
vi.mock('../../components/ScoreChart', () => ({
  ScoreChart: ({ averageData }: { averageData: AverageChartPoint[] }) => (
    <div data-testid="score-chart">
      {averageData.map((point) => point.id).join(',')}
    </div>
  ),
}));

const suite = {
  id: 1,
  name: 'Safety suite',
  eval_type: 'rules',
  subcategory: 'core',
  judge_prompt: '',
  items: {},
  config: {},
  enabled: true,
  created_at: '',
  updated_at: '',
  scenario_count: 1,
};
const event = {
  id: 1,
  correlation_key: 'key',
  agent: 'claude' as const,
  session_id: 'session',
  tool_name: 'Bash',
  cwd: null,
  project: 'agent-smith',
  status: 'success' as const,
  created_at: '',
  completed_at: null,
  duration_ms: 5,
};
const proposal = (
  title = 'Current proposal',
  status: Proposal['status'] = 'pending',
): Proposal => ({
  id: 1,
  title,
  status,
  target_kind: 'rule',
  action: 'update',
  proposed_item_id: 1,
  target_name: 'Rule',
  project: null,
  target_id: null,
  base_version: null,
  rationale: '',
  evidence: [],
  applied_ref: null,
  created_at: '',
  updated_at: '',
});
const run = (scenario = 'Current scenario'): EvalRun => ({
  id: 1,
  timestamp: '',
  eval_type: 'rules',
  subcategory: 'core',
  scenario,
  test_model: 'Model A',
  judge_model: 'Judge',
  threshold: 0.7,
  score_avg: 0.9,
  score_count: 2,
  eval_suite_id: null,
  created_at: '',
});

async function settle() {
  await act(async () => {});
}
async function advance(milliseconds = 300) {
  await act(async () => {
    vi.advanceTimersByTime(milliseconds);
  });
}

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.useFakeTimers();
  vi.mocked(api.audit.list).mockResolvedValue({ items: [event], total: 25 });
  vi.mocked(api.audit.counts).mockResolvedValue({
    claude: 25,
    codex: 0,
    gemini: 0,
  });
  vi.mocked(api.evalConfigs.suites.list).mockResolvedValue({
    items: [suite],
    total: 25,
  });
  vi.mocked(api.evalConfigs.suites.update).mockResolvedValue(suite);
  vi.mocked(api.proposals.list).mockResolvedValue({
    items: [proposal()],
    total: 25,
  });
  vi.mocked(api.proposals.counts).mockResolvedValue({
    pending: 25,
    approved: 2,
    rejected: 0,
  });
  vi.mocked(api.proposals.approve).mockResolvedValue(
    proposal('Current proposal', 'approved'),
  );
  vi.mocked(api.evals.categories).mockResolvedValue(['rules', 'skills']);
  vi.mocked(api.evals.subcategories).mockResolvedValue(['core', 'advanced']);
  vi.mocked(api.evals.facets).mockResolvedValue({
    scenarios: ['Current scenario', 'Outside current page'],
    models: ['Model A', 'Model B'],
  });
  vi.mocked(api.evals.list).mockResolvedValue({ items: [run()], total: 25 });
  vi.mocked(api.evals.chart).mockResolvedValue([]);
  vi.mocked(api.evals.chartAverage).mockResolvedValue([]);
});

afterEach(() => vi.useRealTimers());

describe('Maintenance page server controls', () => {
  it('filters and sorts eval suites through guarded pagination', async () => {
    const list = vi.mocked(api.evalConfigs.suites.list);
    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await settle();
    expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: '10' }),
    );
    list.mockClear();
    const input = screen.getByPlaceholderText('Search eval suites...');
    input.focus();
    fireEvent.change(input, { target: { value: 'Safety' } });
    await advance(299);
    expect(list).not.toHaveBeenCalled();
    await advance(1);
    expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: 'Safety', offset: '0' }),
    );
    expect(
      list.mock.calls.some(
        ([params]) => params?.q === 'Safety' && params.offset !== '0',
      ),
    ).toBe(false);
    expect(input).toHaveFocus();
    fireEvent.change(
      screen.getByRole('combobox', { name: 'Suite enabled state' }),
      { target: { value: 'false' } },
    );
    await settle();
    expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: 'Safety', enabled: 'false', offset: '0' }),
    );
    fireEvent.change(
      screen.getByRole('combobox', { name: 'Sort eval suites' }),
      { target: { value: 'updated' } },
    );
    await settle();
    expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ enabled: 'false', sort: 'updated' }),
    );
  });

  it('keeps suite controls mounted when loading fails', async () => {
    vi.mocked(api.evalConfigs.suites.list).mockRejectedValue(
      new Error('Unavailable'),
    );
    renderWithProviders(<EvalSuitesPage />, {
      initialEntries: ['/eval-configs'],
    });
    const input = screen.getByPlaceholderText('Search eval suites...');
    await settle();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Could not load eval suites',
    );
    expect(screen.getByPlaceholderText('Search eval suites...')).toBe(input);
  });

  it('combines audit search, project, agent, status, and sort while hiding global counts', async () => {
    const list = vi.mocked(api.audit.list);
    renderWithProviders(<AuditIndexPage />, { initialEntries: ['/audit'] });
    await settle();
    expect(
      screen.getByRole('option', { name: 'claude (25)' }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await settle();
    fireEvent.change(screen.getByPlaceholderText('Search audit events...'), {
      target: { value: 'Bash' },
    });
    fireEvent.change(screen.getByPlaceholderText('Filter by project...'), {
      target: { value: 'agent-smith' },
    });
    expect(
      screen.queryByRole('option', { name: 'claude (25)' }),
    ).not.toBeInTheDocument();
    await advance();
    expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: 'Bash', project: 'agent-smith' }),
      { limit: 10, offset: 0 },
    );
    fireEvent.change(screen.getByRole('combobox', { name: 'Agent' }), {
      target: { value: 'claude' },
    });
    fireEvent.change(screen.getByRole('combobox', { name: 'Status' }), {
      target: { value: 'error' },
    });
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort' }), {
      target: { value: 'duration' },
    });
    await settle();
    expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({
        q: 'Bash',
        project: 'agent-smith',
        agent: 'claude',
        status: 'error',
        sort: 'duration',
      }),
      { limit: 10, offset: 0 },
    );
  });

  it('combines proposal search, all statuses, and sort without global counts', async () => {
    const list = vi.mocked(api.proposals.list);
    renderWithProviders(<ProposalsIndexPage />, {
      initialEntries: ['/proposals'],
    });
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await settle();
    fireEvent.change(screen.getByPlaceholderText('Search proposals...'), {
      target: { value: 'parser' },
    });
    expect(
      screen.queryByRole('button', { name: 'pending (25)' }),
    ).not.toBeInTheDocument();
    await advance();
    expect(list).toHaveBeenLastCalledWith(
      'pending',
      expect.objectContaining({ q: 'parser', offset: 0 }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'all statuses' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort proposals' }), {
      target: { value: 'title' },
    });
    await settle();
    expect(list).toHaveBeenLastCalledWith(
      undefined,
      expect.objectContaining({ q: 'parser', sort: 'title', offset: 0 }),
    );
  });

  it('hides global audit counts while a status is selected', async () => {
    renderWithProviders(<AuditIndexPage />, { initialEntries: ['/audit'] });
    await settle();
    expect(
      screen.getByRole('option', { name: 'claude (25)' }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Status' }), {
      target: { value: 'error' },
    });
    await settle();
    expect(
      screen.queryByRole('option', { name: 'claude (25)' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'claude' })).toBeInTheDocument();
  });

  it('refreshes the latest proposal criteria when an earlier review finishes', async () => {
    let finishReview!: (value: Proposal) => void;
    vi.mocked(api.proposals.approve).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishReview = resolve;
        }),
    );
    const list = vi.mocked(api.proposals.list);
    list.mockImplementation(async (status) => ({
      items: [
        proposal(
          status === 'approved' ? 'Approved current' : 'Current proposal',
          status === 'approved' ? 'approved' : 'pending',
        ),
      ],
      total: 25,
    }));
    renderWithProviders(<ProposalsIndexPage />, {
      initialEntries: ['/proposals'],
    });
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    fireEvent.click(screen.getByRole('button', { name: 'approved (2)' }));
    await settle();
    await act(async () => {
      finishReview(proposal('Approved current', 'approved'));
    });
    expect(list).toHaveBeenLastCalledWith(
      'approved',
      expect.objectContaining({ offset: 0 }),
    );
    expect(screen.getByText('Approved current')).toBeInTheDocument();
  });

  it('keeps result facets complete and applies matching search criteria to list and chart', async () => {
    const list = vi.mocked(api.evals.list);
    renderWithProviders(<EvalsPage />, {
      initialEntries: [
        '/evals?category=rules&scenario=URL-only&model=URL-model',
      ],
    });
    await settle();
    expect(
      within(
        screen.getByRole('combobox', { name: 'Result scenario' }),
      ).getByRole('option', { name: 'Outside current page' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('combobox', { name: 'Result scenario' }),
    ).toHaveValue('URL-only');
    expect(screen.getByRole('combobox', { name: 'Result model' })).toHaveValue(
      'URL-model',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await settle();
    list.mockClear();
    fireEvent.change(screen.getByPlaceholderText('Search results...'), {
      target: { value: 'semantic' },
    });
    await advance(299);
    expect(list).not.toHaveBeenCalled();
    await advance(1);
    const matching = {
      eval_type: 'rules',
      scenario: 'URL-only',
      model: 'URL-model',
      q: 'semantic',
    };
    expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ ...matching, offset: '0' }),
    );
    expect(api.evals.chartAverage).toHaveBeenLastCalledWith(matching);
    expect(api.evals.facets).toHaveBeenLastCalledWith({
      eval_type: 'rules',
      q: 'semantic',
    });
    fireEvent.change(
      screen.getByRole('combobox', { name: 'Result category' }),
      { target: { value: 'skills' } },
    );
    await settle();
    expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({
        eval_type: 'skills',
        q: 'semantic',
        offset: '0',
      }),
    );
    expect(list.mock.lastCall?.[0]).not.toHaveProperty('scenario');
    fireEvent.click(screen.getByRole('button', { name: 'Scores' }));
    await settle();
    expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort: 'score', offset: '0' }),
    );
  });

  it('rejects old result rows and chart responses after a new search', async () => {
    let finishRows!: (value: Paginated<EvalRun>) => void;
    let finishChart!: (value: AverageChartPoint[]) => void;
    let finishFacets!: (value: {
      scenarios: string[];
      models: string[];
    }) => void;
    vi.mocked(api.evals.list).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishRows = resolve;
        }),
    );
    vi.mocked(api.evals.chartAverage).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishChart = resolve;
        }),
    );
    vi.mocked(api.evals.facets).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFacets = resolve;
        }),
    );
    renderWithProviders(<EvalsPage />, { initialEntries: ['/evals'] });
    const input = screen.getByPlaceholderText('Search results...');
    fireEvent.change(input, { target: { value: 'current' } });
    await advance();
    await act(async () => {
      finishRows({ items: [run('Stale scenario')], total: 1 });
      finishChart([{ id: 99, timestamp: '', score: 0.1 }]);
      finishFacets({ scenarios: ['Stale facet'], models: ['Stale model'] });
    });
    expect(screen.queryByText('Stale scenario')).not.toBeInTheDocument();
    expect(screen.getByTestId('score-chart')).not.toHaveTextContent('99');
    expect(
      screen.queryByRole('option', { name: 'Stale facet' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('option', { name: 'Stale model' }),
    ).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search results...')).toBe(input);
  });

  it.each([
    {
      name: 'audit',
      view: <AuditIndexPage />,
      placeholder: 'Search audit events...',
      fail: () =>
        vi.mocked(api.audit.list).mockRejectedValue(new Error('Unavailable')),
    },
    {
      name: 'proposals',
      view: <ProposalsIndexPage />,
      placeholder: 'Search proposals...',
      fail: () =>
        vi
          .mocked(api.proposals.list)
          .mockRejectedValue(new Error('Unavailable')),
    },
    {
      name: 'results',
      view: <EvalsPage />,
      placeholder: 'Search results...',
      fail: () =>
        vi.mocked(api.evals.list).mockRejectedValue(new Error('Unavailable')),
    },
  ])(
    'keeps $name controls mounted across loading and failure',
    async ({ name, view, placeholder, fail }) => {
      fail();
      renderWithProviders(view, { initialEntries: [maintenanceRoutes[name]] });
      const input = screen.getByPlaceholderText(placeholder);
      await settle();
      expect(screen.getByRole('alert')).toHaveTextContent('Could not load');
      expect(screen.getByPlaceholderText(placeholder)).toBe(input);
      expect(
        screen.queryByText(
          /^No .*found$|^No tool-call events$|^No pending proposals$/,
        ),
      ).not.toBeInTheDocument();
    },
  );

  it.each([
    {
      name: 'audit',
      view: <AuditIndexPage />,
      placeholder: 'Search audit events...',
      oldCell: 'Bash',
      fail: () =>
        vi
          .mocked(api.audit.list)
          .mockRejectedValueOnce(new Error('Unavailable')),
    },
    {
      name: 'suites',
      view: <EvalSuitesPage />,
      placeholder: 'Search eval suites...',
      oldCell: 'Safety suite',
      fail: () =>
        vi
          .mocked(api.evalConfigs.suites.list)
          .mockRejectedValueOnce(new Error('Unavailable')),
    },
    {
      name: 'proposals',
      view: <ProposalsIndexPage />,
      placeholder: 'Search proposals...',
      oldCell: 'Current proposal',
      fail: () =>
        vi
          .mocked(api.proposals.list)
          .mockRejectedValueOnce(new Error('Unavailable')),
    },
    {
      name: 'results',
      view: <EvalsPage />,
      placeholder: 'Search results...',
      oldCell: 'Current scenario',
      fail: () => {
        vi.mocked(api.evals.list).mockRejectedValueOnce(
          new Error('Unavailable'),
        );
        vi.mocked(api.evals.chartAverage).mockRejectedValueOnce(
          new Error('Unavailable'),
        );
      },
    },
  ])(
    'hides previous $name matches and paging when changed criteria fail',
    async ({ name, view, placeholder, oldCell, fail }) => {
      renderWithProviders(view, { initialEntries: [maintenanceRoutes[name]] });
      await settle();
      expect(screen.getByRole('cell', { name: oldCell })).toBeInTheDocument();
      fail();
      fireEvent.change(screen.getByPlaceholderText(placeholder), {
        target: { value: 'unavailable' },
      });
      await advance();
      expect(
        screen.queryByRole('cell', { name: oldCell }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Next' }),
      ).not.toBeInTheDocument();
      expect(screen.getByPlaceholderText(placeholder)).toHaveValue(
        'unavailable',
      );
      if (placeholder === 'Search results...')
        expect(screen.queryByTestId('score-chart')).not.toBeInTheDocument();
    },
  );
});
