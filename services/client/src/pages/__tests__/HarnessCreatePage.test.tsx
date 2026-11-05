import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { HarnessCreatePage } from '../HarnessCreatePage';
import { ApiError } from '../../api';
import { editorFixtures, harnessKinds } from './harnessEditorFixtures';

const { mockNavigate, mockLocation, editor, legacyCreate, legacyMetadata } =
  vi.hoisted(() => ({
    mockNavigate: vi.fn(),
    mockLocation: { pathname: '/harness/rule/new' },
    editor: {
      descriptors: vi.fn(),
      decode: vi.fn(),
      preview: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
    },
    legacyCreate: vi.fn(),
    legacyMetadata: vi.fn(),
  }));
vi.mock('react-router', async (original) => ({
  ...(await original<typeof import('react-router')>()),
  useNavigate: () => mockNavigate,
  useLocation: () => mockLocation,
}));
vi.mock('../../api', async (original) => ({
  ...(await original<typeof import('../../api')>()),
  api: {
    harness: {
      editor,
      assignableAgents: vi.fn().mockResolvedValue({
        agents: ['claude', 'codex', 'gemini'],
        virtual_agents: ['opinion'],
      }),
      items: { create: legacyCreate, updateMetadata: legacyMetadata },
    },
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockLocation.pathname = '/harness/rule/new';
  editor.descriptors.mockResolvedValue(editorFixtures.descriptors);
  editor.create.mockImplementation(
    async (kind: keyof typeof editorFixtures.cases) =>
      editorFixtures.cases[kind].item,
  );
});

describe('HarnessCreatePage guided routes', () => {
  it.each(harnessKinds)(
    'uses independent backend-described fields for %s',
    async (kind) => {
      mockLocation.pathname = `/harness/${kind}/new`;
      renderWithProviders(<HarnessCreatePage />);
      const definition = editorFixtures.descriptors.types[kind];
      expect(
        await screen.findByRole('heading', { name: `New ${definition.label}` }),
      ).toBeVisible();
      expect(screen.getByRole('tab', { name: 'Guided' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      expect(screen.getByRole('tab', { name: 'Raw' })).toBeVisible();
      const mainField = definition.fields.find(
        (field) => field.key === editorFixtures.cases[kind].changed_field,
      )!;
      expect(
        screen.getByLabelText(mainField.label, { exact: true }),
      ).toHaveAttribute('placeholder', mainField.placeholder);
      expect(
        screen.queryByLabelText('Configuration (JSON)'),
      ).not.toBeInTheDocument();
    },
  );

  it.each(harnessKinds)(
    'submits %s through one atomic editor API without frontend assembly',
    async (kind) => {
      mockLocation.pathname = `/harness/${kind}/new`;
      renderWithProviders(<HarnessCreatePage />);
      const name = await screen.findByLabelText('Name', { exact: true });
      fireEvent.change(name, { target: { value: `new_${kind}` } });
      fireEvent.change(screen.getByLabelText('Initial device'), {
        target: { value: 'my-laptop' },
      });
      fireEvent.change(screen.getByLabelText('Initial repository'), {
        target: { value: '/projects/harness' },
      });
      fireEvent.submit(name.closest('form')!);
      await waitFor(() => expect(editor.create).toHaveBeenCalledTimes(1));
      expect(editor.create).toHaveBeenCalledWith(
        kind,
        expect.objectContaining({
          common: expect.objectContaining({
            name: `new_${kind}`,
            project: null,
            device: 'my-laptop',
            repo: '/projects/harness',
          }),
          mode: 'guided',
        }),
      );
      expect(editor.create.mock.calls[0][1]).not.toHaveProperty('content');
      expect(legacyCreate).not.toHaveBeenCalled();
      expect(legacyMetadata).not.toHaveBeenCalled();
      expect(mockNavigate).toHaveBeenCalledWith(
        `/harness/${kind}/${editorFixtures.cases[kind].item.id}`,
        { replace: false },
      );
    },
  );

  it('keeps rule cloning in the atomic create payload', async () => {
    renderWithProviders(<HarnessCreatePage />);
    const name = await screen.findByLabelText('Name', { exact: true });
    fireEvent.change(name, { target: { value: 'review_rule' } });
    fireEvent.click(screen.getByLabelText('Publish as a skill'));
    fireEvent.change(screen.getByLabelText('Skill description / when to use'), {
      target: { value: 'Use when reviewing changes.' },
    });
    fireEvent.submit(name.closest('form')!);
    await waitFor(() => expect(editor.create).toHaveBeenCalled());
    expect(editor.create.mock.calls[0][1]).toMatchObject({
      common: { clone_as_skill: true },
      fields: { clone_description: 'Use when reviewing changes.' },
    });
    expect(legacyMetadata).not.toHaveBeenCalled();
  });

  it('uses backend agent choices including virtual agents', async () => {
    renderWithProviders(<HarnessCreatePage />);
    expect(
      await screen.findByLabelText('opinion', { exact: true }),
    ).not.toBeChecked();
    expect(screen.getByLabelText('claude', { exact: true })).toBeChecked();
    fireEvent.click(screen.getByLabelText('opinion', { exact: true }));
    fireEvent.submit(
      screen.getByLabelText('Name', { exact: true }).closest('form')!,
    );
    await waitFor(() => expect(editor.create).toHaveBeenCalled());
    expect(editor.create.mock.calls[0][1].common.agents).toContain('opinion');
  });

  it('shows a field-specific server validation error and preserves the draft', async () => {
    editor.create.mockRejectedValueOnce(
      new ApiError(
        'common.name must use lowercase letters, digits, and underscores',
        422,
      ),
    );
    renderWithProviders(<HarnessCreatePage />);
    const name = await screen.findByLabelText('Name', { exact: true });
    fireEvent.change(name, { target: { value: 'Invalid-Name' } });
    fireEvent.submit(name.closest('form')!);
    await screen.findAllByRole('alert');
    expect(name).toHaveValue('Invalid-Name');
    expect(name).toHaveAttribute('aria-invalid', 'true');
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it.each(harnessKinds)('cancels %s creation to its list', async (kind) => {
    mockLocation.pathname = `/harness/${kind}/new`;
    renderWithProviders(<HarnessCreatePage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(mockNavigate).toHaveBeenCalledWith(`/harness/${kind}s`);
    expect(editor.create).not.toHaveBeenCalled();
  });
});
