import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import App from '../App';

// Mock all page components as stubs
vi.mock('../pages/HarnessIndexPage', () => ({
  HarnessIndexPage: ({ type }: { type: string }) => <div data-testid="harness-index">HarnessIndex:{type}</div>,
}));

vi.mock('../pages/HarnessDetailPage', () => ({
  HarnessDetailPage: () => <div data-testid="harness-detail">HarnessDetail</div>,
}));

vi.mock('../pages/HarnessCreatePage', () => ({
  HarnessCreatePage: () => <div data-testid="harness-create">HarnessCreate</div>,
}));

vi.mock('../pages/MemoryPage', () => ({
  MemoryPage: () => <div data-testid="memory-page">MemoryPage</div>,
}));

vi.mock('../pages/EvalsPage', () => ({
  EvalsPage: () => <div data-testid="evals-page">EvalsPage</div>,
}));

vi.mock('../pages/EvalDetailPage', () => ({
  EvalDetailPage: () => <div data-testid="eval-detail">EvalDetail</div>,
}));

vi.mock('../pages/PlansIndexPage', () => ({
  PlansIndexPage: () => <div data-testid="plans-index">PlansIndex</div>,
}));

vi.mock('../pages/PlanDetailPage', () => ({
  PlanDetailPage: () => <div data-testid="plan-detail">PlanDetail</div>,
}));

vi.mock('../pages/EvalSuitesPage', () => ({
  EvalSuitesPage: () => <div data-testid="eval-suites">EvalSuites</div>,
}));

vi.mock('../pages/EvalSuiteDetailPage', () => ({
  EvalSuiteDetailPage: () => <div data-testid="eval-suite-detail">EvalSuiteDetail</div>,
}));

vi.mock('../components/Sidebar', () => ({
  Sidebar: () => <nav data-testid="sidebar">Sidebar</nav>,
}));

vi.mock('../components/NotificationBar', () => ({
  NotificationBar: () => <div data-testid="notification-bar">NotificationBar</div>,
}));

function renderApp(initialEntries: string[]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <App />
    </MemoryRouter>,
  );
}

describe('App', () => {
  it('renders sidebar and notification bar', () => {
    renderApp(['/harness/rules']);
    expect(screen.getByTestId('sidebar')).toBeInTheDocument();
    expect(screen.getByTestId('notification-bar')).toBeInTheDocument();
  });

  it('redirects / to /harness/rules', async () => {
    renderApp(['/']);

    await waitFor(() => {
      expect(screen.getByTestId('harness-index')).toBeInTheDocument();
      expect(screen.getByText('HarnessIndex:rule')).toBeInTheDocument();
    });
  });

  it('renders rules page at /harness/rules', async () => {
    renderApp(['/harness/rules']);
    expect(await screen.findByText('HarnessIndex:rule')).toBeInTheDocument();
  });

  it('renders skills page at /harness/skills', async () => {
    renderApp(['/harness/skills']);
    expect(await screen.findByText('HarnessIndex:skill')).toBeInTheDocument();
  });

  it('renders tools page at /harness/tools', async () => {
    renderApp(['/harness/tools']);
    expect(await screen.findByText('HarnessIndex:tool')).toBeInTheDocument();
  });

  it('renders hooks page at /harness/hooks', async () => {
    renderApp(['/harness/hooks']);
    expect(await screen.findByText('HarnessIndex:hook')).toBeInTheDocument();
  });

  it('renders create page at /harness/rule/new', async () => {
    renderApp(['/harness/rule/new']);
    expect(await screen.findByText('HarnessCreate')).toBeInTheDocument();
  });

  it('renders detail page at /harness/:type/:id', async () => {
    renderApp(['/harness/rule/42']);
    expect(await screen.findByText('HarnessDetail')).toBeInTheDocument();
  });

  it('renders memory page at /memory', async () => {
    renderApp(['/memory']);
    expect(await screen.findByText('MemoryPage')).toBeInTheDocument();
  });

  it('renders evals page at /evals', async () => {
    renderApp(['/evals']);
    expect(await screen.findByText('EvalsPage')).toBeInTheDocument();
  });

  it('renders eval detail at /evals/:id', async () => {
    renderApp(['/evals/5']);
    expect(await screen.findByText('EvalDetail')).toBeInTheDocument();
  });

  it('renders plans page at /plans', async () => {
    renderApp(['/plans']);
    expect(await screen.findByText('PlansIndex')).toBeInTheDocument();
  });

  it('renders plan detail at /plans/:id', async () => {
    renderApp(['/plans/1']);
    expect(await screen.findByText('PlanDetail')).toBeInTheDocument();
  });

  it('renders eval configs page at /eval-configs', async () => {
    renderApp(['/eval-configs']);
    expect(await screen.findByText('EvalSuites')).toBeInTheDocument();
  });

  it('renders eval suite detail at /eval-configs/:id', async () => {
    renderApp(['/eval-configs/1']);
    expect(await screen.findByText('EvalSuiteDetail')).toBeInTheDocument();
  });
});
