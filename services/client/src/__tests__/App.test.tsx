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

  it('renders rules page at /harness/rules', () => {
    renderApp(['/harness/rules']);
    expect(screen.getByText('HarnessIndex:rule')).toBeInTheDocument();
  });

  it('renders skills page at /harness/skills', () => {
    renderApp(['/harness/skills']);
    expect(screen.getByText('HarnessIndex:skill')).toBeInTheDocument();
  });

  it('renders tools page at /harness/tools', () => {
    renderApp(['/harness/tools']);
    expect(screen.getByText('HarnessIndex:tool')).toBeInTheDocument();
  });

  it('renders hooks page at /harness/hooks', () => {
    renderApp(['/harness/hooks']);
    expect(screen.getByText('HarnessIndex:hook')).toBeInTheDocument();
  });

  it('renders create page at /harness/rule/new', () => {
    renderApp(['/harness/rule/new']);
    expect(screen.getByText('HarnessCreate')).toBeInTheDocument();
  });

  it('renders detail page at /harness/:type/:id', () => {
    renderApp(['/harness/rule/42']);
    expect(screen.getByText('HarnessDetail')).toBeInTheDocument();
  });

  it('renders memory page at /memory', () => {
    renderApp(['/memory']);
    expect(screen.getByText('MemoryPage')).toBeInTheDocument();
  });

  it('renders evals page at /evals', () => {
    renderApp(['/evals']);
    expect(screen.getByText('EvalsPage')).toBeInTheDocument();
  });

  it('renders eval detail at /evals/:id', () => {
    renderApp(['/evals/5']);
    expect(screen.getByText('EvalDetail')).toBeInTheDocument();
  });

  it('renders plans page at /plans', () => {
    renderApp(['/plans']);
    expect(screen.getByText('PlansIndex')).toBeInTheDocument();
  });

  it('renders plan detail at /plans/:id', () => {
    renderApp(['/plans/1']);
    expect(screen.getByText('PlanDetail')).toBeInTheDocument();
  });

  it('renders eval configs page at /eval-configs', () => {
    renderApp(['/eval-configs']);
    expect(screen.getByText('EvalSuites')).toBeInTheDocument();
  });

  it('renders eval suite detail at /eval-configs/:id', () => {
    renderApp(['/eval-configs/1']);
    expect(screen.getByText('EvalSuiteDetail')).toBeInTheDocument();
  });
});
