import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { HarnessDetailPage } from '../HarnessDetailPage';
import { ApiError } from '../../api';
import { editorFixtures, harnessKinds } from './harnessEditorFixtures';

vi.mock('react-markdown', () => ({
  default: ({ children }: any) => (
    <div data-testid="markdown-content">{children}</div>
  ),
}));

vi.mock('remark-gfm', () => ({ default: {} }));

const { mockNavigate, mockParams } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockParams: { type: 'rule', id: '1' } as Record<string, string>,
}));

vi.mock('react-router', async () => {
  const actual =
    await vi.importActual<typeof import('react-router')>('react-router');
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
  const actual = await vi.importActual<
    typeof import('../../context/useNotification')
  >('../../context/useNotification');
  return {
    ...actual,
    useNotification: () => ({
      notify: mockNotify,
      notifications: [],
      dismiss: vi.fn(),
    }),
  };
});

const {
  mockGet,
  mockUpdateContent,
  mockUpdateMetadata,
  mockHistory,
  mockRemove,
  mockConfigsAdd,
  mockConfigsUpdate,
  mockConfigsRemove,
  mockAssignableAgents,
  editor,
} = vi.hoisted(() => ({
  editor: {
    descriptors: vi.fn(),
    decode: vi.fn(),
    preview: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
  },
  mockAssignableAgents: vi.fn(),
  mockGet: vi.fn(),
  mockUpdateContent: vi.fn(),
  mockUpdateMetadata: vi.fn(),
  mockHistory: vi.fn(),
  mockRemove: vi.fn(),
  mockConfigsAdd: vi.fn(),
  mockConfigsUpdate: vi.fn(),
  mockConfigsRemove: vi.fn(),
}));

vi.mock('../../api', async (original) => ({
  ...(await original<typeof import('../../api')>()),
  api: {
    harness: {
      editor,
      assignableAgents: mockAssignableAgents,
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
  vi.resetAllMocks();
  editor.descriptors.mockResolvedValue(editorFixtures.descriptors);
  editor.decode.mockResolvedValue(
    structuredClone(editorFixtures.cases.rule.draft),
  );
  editor.update.mockResolvedValue(makeItem());
  mockParams.type = 'rule';
  mockParams.id = '1';
  mockGet.mockResolvedValue(makeItem());
  mockHistory.mockResolvedValue(makeHistory());
  mockAssignableAgents.mockResolvedValue({
    agents: ['claude', 'codex', 'gemini'],
    virtual_agents: ['opinion'],
  });
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

  it.each(harnessKinds)(
    'edits %s through the shared guided form and atomic snapshot API',
    async (kind) => {
      const example = editorFixtures.cases[kind];
      mockParams.type = kind;
      mockParams.id = String(example.item.id);
      mockGet.mockResolvedValue(example.item);
      mockHistory.mockResolvedValue([example.item]);
      editor.decode.mockResolvedValue(structuredClone(example.draft));
      editor.update.mockResolvedValue(example.updated);
      renderWithProviders(<HarnessDetailPage />);
      fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
      const descriptor = editorFixtures.descriptors.types[kind].fields.find(
        (field) => field.key === example.changed_field,
      )!;
      const input = await screen.findByLabelText(descriptor.label, {
        exact: true,
      });
      expect(input).toHaveValue(String(example.fields[example.changed_field]));
      expect(screen.getByRole('tab', { name: 'Guided' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      expect(screen.queryByLabelText('Initial device')).not.toBeInTheDocument();
      fireEvent.change(input, { target: { value: example.updated_value } });
      fireEvent.submit(input.closest('form')!);
      await waitFor(() => expect(editor.update).toHaveBeenCalledTimes(1));
      expect(editor.update).toHaveBeenCalledWith(
        kind,
        example.item.id,
        expect.objectContaining({
          expected_version: example.item.version,
          expected_updated_at: example.item.updated_at,
          original_content: example.item.content,
          extensions: example.draft.extensions,
          dirty_paths: [`/fields/${example.changed_field}`],
          common: expect.objectContaining({
            name: example.item.name,
            agents: example.item.agents,
          }),
        }),
      );
      expect(mockUpdateContent).not.toHaveBeenCalled();
      expect(mockUpdateMetadata).not.toHaveBeenCalled();
      expect(mockNavigate).toHaveBeenCalledWith(
        `/harness/${kind}/${example.updated.id}`,
        { replace: true },
      );
    },
  );

  it('sends content and common metadata together without partial legacy writes', async () => {
    renderWithProviders(<HarnessDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const instructions = await screen.findByLabelText('Instructions', {
      exact: true,
    });
    fireEvent.change(instructions, {
      target: { value: 'Complete revised instructions.' },
    });
    fireEvent.change(screen.getByLabelText('Project'), {
      target: { value: 'harness' },
    });
    fireEvent.click(screen.getByLabelText('Enabled', { exact: true }));
    fireEvent.submit(instructions.closest('form')!);
    await waitFor(() => expect(editor.update).toHaveBeenCalledTimes(1));
    expect(editor.update.mock.calls[0][2]).toMatchObject({
      common: { project: 'harness', enabled: false },
      fields: { instructions: 'Complete revised instructions.' },
      expected_version: 3,
      expected_updated_at: '2026-01-01T00:00:00Z',
    });
    expect(mockUpdateContent).not.toHaveBeenCalled();
    expect(mockUpdateMetadata).not.toHaveBeenCalled();
  });

  it('refreshes the same saved identity and history after a no-change save', async () => {
    renderWithProviders(<HarnessDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const input = await screen.findByLabelText('Instructions', { exact: true });
    fireEvent.submit(input.closest('form')!);
    await screen.findByRole('button', { name: 'Edit' });
    expect(mockGet).toHaveBeenCalledTimes(2);
    expect(mockHistory).toHaveBeenCalledTimes(2);
    expect(editor.update.mock.calls[0][2].dirty_paths).toEqual([]);
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('retains the displayed snapshot and unsaved content after a conflict', async () => {
    editor.update.mockRejectedValueOnce(
      new ApiError(
        'This item changed; reopen the latest version before retrying.',
        409,
      ),
    );
    renderWithProviders(<HarnessDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const input = await screen.findByLabelText('Instructions', { exact: true });
    fireEvent.change(input, { target: { value: 'Keep this unsaved draft.' } });
    fireEvent.submit(input.closest('form')!);
    await screen.findByRole('alert');
    expect(input).toHaveValue('Keep this unsaved draft.');
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(editor.update).toHaveBeenCalledTimes(1);
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('cancels guided editing back to the existing history and configuration view', async () => {
    renderWithProviders(<HarnessDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    await screen.findByLabelText('Instructions', { exact: true });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByText('Version History')).toBeVisible();
    expect(screen.getByText('Configurations')).toBeVisible();
    expect(screen.getByText('test_rule')).toBeVisible();
    expect(editor.update).not.toHaveBeenCalled();
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
      expect(
        screen.getByText('No version history available'),
      ).toBeInTheDocument();
    });
  });

  it('shows config section with add button', async () => {
    renderWithProviders(<HarnessDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('Configurations')).toBeInTheDocument();
    });

    expect(
      screen.getByText('No configurations — using legacy defaults'),
    ).toBeInTheDocument();
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
