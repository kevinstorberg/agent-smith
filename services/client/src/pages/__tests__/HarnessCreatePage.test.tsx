import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { HarnessCreatePage } from '../HarnessCreatePage';

vi.mock('@uiw/react-md-editor', () => ({
  default: (props: any) => (
    <textarea
      data-testid="md-editor"
      value={props.value}
      onChange={(e: any) => props.onChange?.(e.target.value)}
    />
  ),
}));

const { mockNavigate, mockLocation } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockLocation: { pathname: '/harness/rule/new' },
}));

vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useLocation: () => mockLocation,
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

const { mockCreate, mockUpdateMetadata, mockAssignableAgents } = vi.hoisted(() => ({
  mockCreate: vi.fn(),
  mockUpdateMetadata: vi.fn(),
  mockAssignableAgents: vi.fn(),
}));

vi.mock('../../api', () => ({
  api: {
    harness: {
      assignableAgents: mockAssignableAgents,
      items: {
        create: mockCreate,
        updateMetadata: mockUpdateMetadata,
      },
    },
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockLocation.pathname = '/harness/rule/new';
  mockCreate.mockResolvedValue({ id: 99 });
  mockUpdateMetadata.mockResolvedValue({});
  mockAssignableAgents.mockResolvedValue({
    agents: ['claude', 'codex', 'gemini'],
    virtual_agents: ['opinion'],
  });
});

describe('HarnessCreatePage', () => {
  it('derives type from URL path - rule', () => {
    mockLocation.pathname = '/harness/rule/new';
    renderWithProviders(<HarnessCreatePage />);
    expect(screen.getByText('New Rule')).toBeInTheDocument();
  });

  it('renders virtual agents from the API, unchecked by default', async () => {
    renderWithProviders(<HarnessCreatePage />);
    const opinionCheckbox = await screen.findByLabelText(/opinion/);
    expect(opinionCheckbox).not.toBeChecked();
    expect(screen.getByLabelText('claude')).toBeChecked();
  });

  it('derives type from URL path - tool', () => {
    mockLocation.pathname = '/harness/tool/new';
    renderWithProviders(<HarnessCreatePage />);
    expect(screen.getByText('New Tool')).toBeInTheDocument();
  });

  it('derives type from URL path - hook', () => {
    mockLocation.pathname = '/harness/hook/new';
    renderWithProviders(<HarnessCreatePage />);
    expect(screen.getByText('New Hook')).toBeInTheDocument();
  });

  it('validates name is required', () => {
    renderWithProviders(<HarnessCreatePage />);
    fireEvent.click(screen.getByText('Create Rule'));
    expect(mockNotify).toHaveBeenCalledWith('Name is required.', 'error');
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('validates name format - lowercase only', () => {
    renderWithProviders(<HarnessCreatePage />);

    const nameInput = document.querySelector('input[maxlength]') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'Invalid-Name' } });

    fireEvent.click(screen.getByText('Create Rule'));

    expect(mockNotify).toHaveBeenCalledWith(
      'Name must be lowercase letters, digits, and underscores only.',
      'error',
    );
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('validates at least one agent is selected', () => {
    renderWithProviders(<HarnessCreatePage />);

    const nameInput = document.querySelector('input[maxlength]') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'valid_name' } });

    // Uncheck all agents
    const agentCheckboxes = screen.getAllByRole('checkbox').filter(cb => {
      const label = cb.closest('label');
      return label?.textContent && ['claude', 'codex', 'gemini'].includes(label.textContent.trim());
    });
    agentCheckboxes.forEach(cb => {
      if ((cb as HTMLInputElement).checked) fireEvent.click(cb);
    });

    fireEvent.click(screen.getByText('Create Rule'));

    expect(mockNotify).toHaveBeenCalledWith('At least one agent must be selected.', 'error');
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('shows markdown editor for rule type', () => {
    mockLocation.pathname = '/harness/rule/new';
    renderWithProviders(<HarnessCreatePage />);
    expect(screen.getByTestId('md-editor')).toBeInTheDocument();
    expect(screen.getByText('Body')).toBeInTheDocument();
  });

  it('shows JSON textarea for tool type', () => {
    mockLocation.pathname = '/harness/tool/new';
    renderWithProviders(<HarnessCreatePage />);
    expect(screen.queryByTestId('md-editor')).not.toBeInTheDocument();
    expect(screen.getByText('Configuration (JSON)')).toBeInTheDocument();
  });

  it('shows JSON textarea for hook type', () => {
    mockLocation.pathname = '/harness/hook/new';
    renderWithProviders(<HarnessCreatePage />);
    expect(screen.queryByTestId('md-editor')).not.toBeInTheDocument();
    expect(screen.getByText('Configuration (JSON)')).toBeInTheDocument();
  });

  it('creates a rule and navigates to detail page', async () => {
    renderWithProviders(<HarnessCreatePage />);

    const nameInput = document.querySelector('input[maxlength]') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'my_new_rule' } });

    fireEvent.click(screen.getByText('Create Rule'));

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith(
        'rule',
        expect.objectContaining({ name: 'my_new_rule' }),
      );
      expect(mockNavigate).toHaveBeenCalledWith('/harness/rule/99');
    });
  });

  it('calls updateMetadata for clone_as_skill when checked for rules', async () => {
    renderWithProviders(<HarnessCreatePage />);

    const nameInput = document.querySelector('input[maxlength]') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'my_rule' } });

    const cloneCheckbox = screen.getAllByRole('checkbox').find(cb => {
      const label = cb.closest('label');
      return label?.textContent?.trim() === 'Clone as Skill';
    });
    expect(cloneCheckbox).toBeDefined();
    fireEvent.click(cloneCheckbox!);

    fireEvent.click(screen.getByText('Create Rule'));

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalled();
      expect(mockUpdateMetadata).toHaveBeenCalledWith('rule', 99, { clone_as_skill: true });
    });
  });

  it('validates JSON for non-markdown types', () => {
    mockLocation.pathname = '/harness/tool/new';
    renderWithProviders(<HarnessCreatePage />);

    const nameInput = document.querySelector('input[maxlength]') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'my_api' } });

    const textarea = document.querySelector('textarea[spellcheck="false"]') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'not json' } });

    fireEvent.click(screen.getByText('Create Tool'));

    expect(mockNotify).toHaveBeenCalledWith('Invalid JSON in metadata field.', 'error');
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('navigates back on cancel', () => {
    renderWithProviders(<HarnessCreatePage />);
    fireEvent.click(screen.getByText('Cancel'));
    expect(mockNavigate).toHaveBeenCalledWith('/harness/rules');
  });
});
