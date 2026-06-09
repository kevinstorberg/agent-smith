import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { EvalSuiteDetailPage } from '../EvalSuiteDetailPage';

const { mockNavigate, mockParams } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockParams: { id: '1' } as Record<string, string>,
}));

vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => mockParams,
  };
});

const { mockNotify } = vi.hoisted(() => ({
  mockNotify: vi.fn(),
}));

vi.mock('../../context/useNotification', async () => {
  const actual = await vi.importActual<typeof import('../../context/useNotification')>('../../context/useNotification');
  return {
    ...actual,
    useNotification: () => ({ notify: mockNotify, notifications: [], dismiss: vi.fn() }),
  };
});

const { mockSuiteGet, mockSuiteCreate, mockSuiteUpdate, mockSuiteRemove, mockScenarioCreate, mockScenarioUpdate, mockScenarioRemove } = vi.hoisted(() => ({
  mockSuiteGet: vi.fn(),
  mockSuiteCreate: vi.fn(),
  mockSuiteUpdate: vi.fn(),
  mockSuiteRemove: vi.fn(),
  mockScenarioCreate: vi.fn(),
  mockScenarioUpdate: vi.fn(),
  mockScenarioRemove: vi.fn(),
}));

vi.mock('../../api', () => ({
  api: {
    evalConfigs: {
      suites: {
        get: mockSuiteGet,
        create: mockSuiteCreate,
        update: mockSuiteUpdate,
        remove: mockSuiteRemove,
      },
      scenarios: {
        create: mockScenarioCreate,
        update: mockScenarioUpdate,
        remove: mockScenarioRemove,
      },
    },
  },
}));

function makeSuite(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: 'Test Suite',
    eval_type: 'rules',
    subcategory: 'core',
    judge_prompt: 'Judge this output',
    items: { key: 'value' },
    config: { threshold: 0.7 },
    enabled: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    scenarios: [
      {
        id: 10,
        suite_id: 1,
        name: 'scenario_one',
        prompt: 'A '.repeat(100),
        enabled: true,
        sort_key: 0,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockParams.id = '1';
  mockSuiteGet.mockResolvedValue(makeSuite());
});

describe('EvalSuiteDetailPage', () => {
  it('renders in create mode when id is "new"', () => {
    mockParams.id = 'new';
    renderWithProviders(<EvalSuiteDetailPage />);

    expect(screen.getByPlaceholderText('Suite name')).toBeInTheDocument();
    expect(screen.getByText('Save')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('renders view mode with suite data', async () => {
    renderWithProviders(<EvalSuiteDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Test Suite')).toBeInTheDocument();
    });

    expect(screen.getByText('rules / core')).toBeInTheDocument();
    expect(screen.getByText('Judge this output')).toBeInTheDocument();
    expect(screen.getByText('scenario_one')).toBeInTheDocument();
  });

  it('validates required fields on save in create mode', () => {
    mockParams.id = 'new';
    renderWithProviders(<EvalSuiteDetailPage />);

    fireEvent.click(screen.getByText('Save'));

    expect(mockNotify).toHaveBeenCalledWith('Name is required.', 'error');
    expect(mockSuiteCreate).not.toHaveBeenCalled();
  });

  it('validates JSON fields on save', () => {
    mockParams.id = 'new';
    renderWithProviders(<EvalSuiteDetailPage />);

    fireEvent.change(screen.getByPlaceholderText('Suite name'), { target: { value: 'My Suite' } });

    const textInputs = document.querySelectorAll('input[type="text"]');
    fireEvent.change(textInputs[1], { target: { value: 'rules' } });
    fireEvent.change(textInputs[2], { target: { value: 'core' } });

    const textareas = document.querySelectorAll('textarea');
    fireEvent.change(textareas[0], { target: { value: 'judge prompt' } });
    fireEvent.change(textareas[1], { target: { value: 'not valid json' } });

    fireEvent.click(screen.getByText('Save'));

    expect(mockNotify).toHaveBeenCalledWith('Invalid JSON in Items field', 'error');
    expect(mockSuiteCreate).not.toHaveBeenCalled();
  });

  it('creates a new suite and navigates on success', async () => {
    mockParams.id = 'new';
    mockSuiteCreate.mockResolvedValue({ id: 5 });
    renderWithProviders(<EvalSuiteDetailPage />);

    fireEvent.change(screen.getByPlaceholderText('Suite name'), { target: { value: 'New Suite' } });

    const textInputs = document.querySelectorAll('input[type="text"]');
    fireEvent.change(textInputs[1], { target: { value: 'rules' } });
    fireEvent.change(textInputs[2], { target: { value: 'core' } });

    const textareas = document.querySelectorAll('textarea');
    fireEvent.change(textareas[0], { target: { value: 'Judge this' } });

    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(mockSuiteCreate).toHaveBeenCalled();
      expect(mockNavigate).toHaveBeenCalledWith('/eval-configs/5', { replace: true });
    });
  });

  it('adds a scenario with validation', async () => {
    renderWithProviders(<EvalSuiteDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('+ Add Scenario')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('+ Add Scenario'));

    // Try to add without name
    fireEvent.click(screen.getByText('Add'));
    expect(mockNotify).toHaveBeenCalledWith('Scenario name is required.', 'error');

    // Fill name but no prompt
    const nameInput = screen.getByPlaceholderText('scenario_name');
    fireEvent.change(nameInput, { target: { value: 'new_scenario' } });
    fireEvent.click(screen.getByText('Add'));
    expect(mockNotify).toHaveBeenCalledWith('Scenario prompt is required.', 'error');

    // Fill prompt and add
    const promptArea = screen.getByPlaceholderText('Scenario prompt...');
    fireEvent.change(promptArea, { target: { value: 'Test prompt' } });

    mockScenarioCreate.mockResolvedValue({
      id: 20,
      suite_id: 1,
      name: 'new_scenario',
      prompt: 'Test prompt',
      enabled: true,
      sort_key: 0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });

    fireEvent.click(screen.getByText('Add'));

    await waitFor(() => {
      expect(mockScenarioCreate).toHaveBeenCalledWith(1, {
        name: 'new_scenario',
        prompt: 'Test prompt',
        enabled: true,
      });
    });
  });

  it('deletes a scenario after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    mockScenarioRemove.mockResolvedValue({ deleted: 1 });

    renderWithProviders(<EvalSuiteDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('scenario_one')).toBeInTheDocument();
    });

    // The scenario Delete button is inside the table
    const deleteBtns = screen.getAllByRole('button', { name: 'Delete' });
    // The first Delete is the suite delete, the second is the scenario
    const scenarioDeleteBtn = deleteBtns.find(b => b.style.fontSize === '11px' || b.closest('td'));
    fireEvent.click(scenarioDeleteBtn || deleteBtns[deleteBtns.length - 1]);

    await waitFor(() => {
      expect(mockScenarioRemove).toHaveBeenCalledWith(10);
    });

    vi.restoreAllMocks();
  });

  it('deletes the suite after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    mockSuiteRemove.mockResolvedValue({ deleted: 1 });

    renderWithProviders(<EvalSuiteDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Test Suite')).toBeInTheDocument();
    });

    const buttons = screen.getAllByRole('button');
    const deleteSuiteBtn = buttons.find(b => b.textContent === 'Delete' && b.className.includes('btn-danger'));
    expect(deleteSuiteBtn).toBeDefined();
    fireEvent.click(deleteSuiteBtn!);

    await waitFor(() => {
      expect(mockSuiteRemove).toHaveBeenCalledWith(1);
      expect(mockNavigate).toHaveBeenCalledWith('/eval-configs');
    });

    vi.restoreAllMocks();
  });
});
