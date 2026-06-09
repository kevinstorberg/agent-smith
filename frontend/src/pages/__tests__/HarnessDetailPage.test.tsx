import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { HarnessDetailPage } from '../HarnessDetailPage';

vi.mock('@uiw/react-md-editor', () => ({
  default: (props: any) => (
    <textarea
      data-testid="md-editor"
      value={props.value}
      onChange={(e: any) => props.onChange?.(e.target.value)}
    />
  ),
}));

vi.mock('react-markdown', () => ({
  default: ({ children }: any) => <div data-testid="markdown-content">{children}</div>,
}));

vi.mock('remark-gfm', () => ({ default: {} }));

const { mockNavigate, mockParams } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockParams: { type: 'rule', id: '1' } as Record<string, string>,
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

const { mockGet, mockUpdateContent, mockUpdateMetadata, mockHistory, mockRemove, mockConfigsAdd, mockConfigsUpdate, mockConfigsRemove } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockUpdateContent: vi.fn(),
  mockUpdateMetadata: vi.fn(),
  mockHistory: vi.fn(),
  mockRemove: vi.fn(),
  mockConfigsAdd: vi.fn(),
  mockConfigsUpdate: vi.fn(),
  mockConfigsRemove: vi.fn(),
}));

vi.mock('../../api', () => ({
  api: {
    harness: {
      items: {
        get: mockGet,
        updateContent: mockUpdateContent,
        updateMetadata: mockUpdateMetadata,
        history: mockHistory,
        remove: mockRemove,
        configs: {
          add: mockConfigsAdd,
          update: mockConfigsUpdate,
          remove: mockConfigsRemove,
        },
      },
    },
  },
}));

vi.mock('../../components/ConfigForm', () => ({
  ConfigForm: (props: any) => (
    <div data-testid="config-form">
      <button onClick={props.onSave}>SaveConfig</button>
      <button onClick={props.onCancel}>CancelConfig</button>
    </div>
  ),
}));

function makeItem(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: 'test_rule',
    project: null,
    agents: ['claude'],
    content: { body: '# Hello World', metadata: {} },
    sort_key: 5,
    enabled: true,
    clone_as_skill: false,
    version: 3,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    configs: [],
    ...overrides,
  };
}

function makeHistory() {
  return [
    makeItem({ id: 1, version: 3 }),
    makeItem({ id: 100, version: 2 }),
    makeItem({ id: 99, version: 1 }),
  ];
}

beforeEach(() => {
  vi.clearAllMocks();
  mockParams.type = 'rule';
  mockParams.id = '1';
  mockGet.mockResolvedValue(makeItem());
  mockHistory.mockResolvedValue(makeHistory());
  mockUpdateContent.mockResolvedValue(makeItem({ id: 2, version: 4 }));
  mockUpdateMetadata.mockResolvedValue(makeItem());
  mockConfigsAdd.mockResolvedValue({ id: 50 });
});

describe('HarnessDetailPage', () => {
  it('renders view mode with item data', async () => {
    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    expect(screen.getByText('test_rule')).toBeInTheDocument();
    expect(screen.getByText('Enabled')).toBeInTheDocument();
    expect(screen.getByText('claude')).toBeInTheDocument();
  });

  it('enters edit mode and shows editor', async () => {
    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Edit')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Edit'));

    expect(await screen.findByTestId('md-editor')).toBeInTheDocument();
    expect(screen.getByText('Save')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('validates name on save', async () => {
    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Edit')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Edit'));

    const nameInput = document.querySelector('input[maxlength]') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: '' } });

    fireEvent.click(screen.getByText('Save'));

    expect(mockNotify).toHaveBeenCalledWith('Name is required.', 'error');
    expect(mockUpdateContent).not.toHaveBeenCalled();
    expect(mockUpdateMetadata).not.toHaveBeenCalled();
  });

  it('validates JSON for non-markdown types', async () => {
    mockParams.type = 'tool';
    const toolItem = makeItem({
      content: { body: '', metadata: { url: 'https://test.com' } },
    });
    mockGet.mockResolvedValue(toolItem);

    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Edit')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Edit'));

    const textarea = document.querySelector('textarea[spellcheck="false"]') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'not valid json' } });

    fireEvent.click(screen.getByText('Save'));

    expect(mockNotify).toHaveBeenCalledWith('Invalid JSON in metadata field.', 'error');
    expect(mockUpdateContent).not.toHaveBeenCalled();
  });

  it('saves body change only (calls updateContent, not updateMetadata)', async () => {
    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Edit')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Edit'));

    const editor = screen.getByTestId('md-editor') as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: '# Updated content' } });

    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(mockUpdateContent).toHaveBeenCalledWith(
        'rule',
        1,
        expect.objectContaining({ body: '# Updated content' }),
      );
      expect(mockUpdateMetadata).not.toHaveBeenCalled();
    });
  });

  it('saves metadata change only (calls updateMetadata, not updateContent)', async () => {
    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Edit')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Edit'));

    const enabledCheckbox = screen.getAllByRole('checkbox').find(cb => {
      const label = cb.closest('label');
      return label?.textContent?.trim() === 'Enabled';
    });
    expect(enabledCheckbox).toBeDefined();
    fireEvent.click(enabledCheckbox!);

    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(mockUpdateContent).not.toHaveBeenCalled();
      expect(mockUpdateMetadata).toHaveBeenCalledWith(
        'rule',
        1,
        expect.objectContaining({ enabled: false }),
      );
    });
  });

  it('renders version history', async () => {
    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Version History')).toBeInTheDocument();
    });

    const v3Elements = screen.getAllByText('v3');
    expect(v3Elements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('v2')).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
    expect(screen.getByText('current')).toBeInTheDocument();
  });

  it('shows empty version history message', async () => {
    mockHistory.mockResolvedValue([]);

    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('No version history available')).toBeInTheDocument();
    });
  });

  it('shows config section with add button', async () => {
    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Configurations')).toBeInTheDocument();
    });

    expect(screen.getByText('No configurations — using legacy defaults')).toBeInTheDocument();
    expect(screen.getByText('+ Add')).toBeInTheDocument();
  });

  it('opens config form on add click', async () => {
    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('+ Add')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('+ Add'));

    expect(screen.getByTestId('config-form')).toBeInTheDocument();
  });

  it('deletes item after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    mockRemove.mockResolvedValue(undefined);

    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    const deleteBtn = screen.getByRole('button', { name: 'Delete' });
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(mockRemove).toHaveBeenCalledWith('rule', 1);
    });

    vi.restoreAllMocks();
  });

  it('renders existing configs', async () => {
    const itemWithConfigs = makeItem({
      configs: [
        {
          id: 10,
          device: 'macbook',
          repo: '/Users/me/project',
          agents: ['claude'],
          subagents: [],
          enabled: true,
          exclude: false,
        },
      ],
    });
    mockGet.mockResolvedValue(itemWithConfigs);

    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('macbook')).toBeInTheDocument();
    });

    expect(screen.getByText('Include')).toBeInTheDocument();
    expect(screen.getByText('/Users/me/project')).toBeInTheDocument();
  });
});
