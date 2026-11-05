import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { HarnessEditor } from '../HarnessEditor';
import { ApiError, api } from '../../api';
import type { HarnessItem } from '../../api';
import type {
  HarnessDraft,
  EditorDescriptors,
} from '../../types/harnessEditor';

vi.mock('../../api', async (original) => ({
  ...(await original<typeof import('../../api')>()),
  api: {
    harness: {
      editor: {
        descriptors: vi.fn(),
        decode: vi.fn(),
        preview: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
      },
    },
  },
}));

const descriptors: EditorDescriptors = {
  common: [
    {
      key: 'name',
      label: 'Name',
      kind: 'text',
      placeholder: 'review_changes',
      required: true,
      default: '',
    },
    {
      key: 'project',
      label: 'Project',
      kind: 'text',
      placeholder: 'agent-smith',
      default: '',
    },
    {
      key: 'agents',
      label: 'Available to agents',
      kind: 'multiselect',
      placeholder: 'Choose agents',
      choices: ['claude', 'codex'],
      default: ['claude'],
    },
  ],
  types: {
    skill: {
      label: 'Skill',
      initial_extensions: { frontmatter: {}, metadata: {} },
      fields: [
        {
          key: 'description',
          label: 'Description / when to use',
          kind: 'text',
          placeholder: 'Use when reviewing changes.',
          required: true,
          default: '',
        },
        {
          key: 'instructions',
          label: 'Instructions',
          kind: 'markdown',
          placeholder: 'Read complete changes and report findings.',
          required: true,
          default: '',
        },
        {
          key: 'files',
          label: 'Supporting files',
          kind: 'rows',
          placeholder: 'references/checklist.md',
          default: [],
          fields: [
            {
              key: 'path',
              label: 'File path',
              kind: 'text',
              placeholder: 'references/checklist.md',
            },
            {
              key: 'content',
              label: 'File content',
              kind: 'markdown',
              placeholder: '# Checklist',
            },
          ],
        },
      ],
    },
  },
};
const item: HarnessItem = {
  id: 1,
  name: 'sample',
  project: null,
  agents: ['claude'],
  sort_key: 0,
  enabled: true,
  version: 3,
  updated_at: '2026-11-05T12:00:00.123456Z',
  created_at: '2026-11-05T12:00:00Z',
  configs: [],
  content: {
    body: '---\n# Preserve comment\nname: sample\ndescription: Review changes\ncustom: keep\n---\nComplete instructions.',
    metadata: { files: {}, custom: { empty: '', enabled: false } },
  },
};
const draft: HarnessDraft = {
  fields: {
    description: 'Review changes',
    instructions: 'Complete instructions.',
    files: [],
  },
  extensions: {
    frontmatter: { custom: 'keep' },
    metadata: { custom: { empty: '', enabled: false } },
  },
  original_content: item.content,
  raw: item.content!.body,
  capabilities: { guided_supported: true, unsupported_paths: [] },
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.harness.editor.descriptors).mockResolvedValue(descriptors);
  vi.mocked(api.harness.editor.decode).mockResolvedValue(
    structuredClone(draft),
  );
  vi.mocked(api.harness.editor.create).mockResolvedValue(item);
  vi.mocked(api.harness.editor.update).mockResolvedValue(item);
  vi.mocked(api.harness.editor.preview).mockResolvedValue({
    content: item.content,
    draft: structuredClone(draft),
  });
});

describe('HarnessEditor Skills vertical tracer', () => {
  it('associates actual parsed common validation errors with their described field', async () => {
    vi.mocked(api.harness.editor.update).mockRejectedValue(
      new ApiError(
        'name: Value error, Name must use lowercase letters, numbers, and underscores',
        422,
      ),
    );
    renderWithProviders(<HarnessEditor kind="skill" item={item} />);
    const name = await screen.findByLabelText('Name');
    fireEvent.change(name, { target: { value: 'Invalid Name' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Skill' }));
    await waitFor(() => expect(name).toHaveAttribute('aria-invalid', 'true'));
    expect(name).toHaveAccessibleDescription(
      expect.stringContaining('Name must use lowercase'),
    );
    expect(name).toHaveValue('Invalid Name');
  });

  it('creates using independent described fields and sends data for backend assembly', async () => {
    const saved = vi.fn();
    renderWithProviders(<HarnessEditor kind="skill" onSaved={saved} />);
    fireEvent.change(await screen.findByLabelText('Name'), {
      target: { value: 'sample' },
    });
    fireEvent.change(screen.getByLabelText('Description / when to use'), {
      target: { value: 'Review changes' },
    });
    fireEvent.change(screen.getByLabelText('Instructions'), {
      target: { value: 'Complete instructions.' },
    });
    expect(
      screen.getByPlaceholderText('Use when reviewing changes.'),
    ).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Create Skill' }));
    await waitFor(() => expect(saved).toHaveBeenCalledWith(item));
    const request = vi.mocked(api.harness.editor.create).mock.calls[0][1];
    expect(request).toMatchObject({
      common: { name: 'sample', agents: ['claude'] },
      mode: 'guided',
      fields: {
        description: 'Review changes',
        instructions: 'Complete instructions.',
      },
    });
    expect(request).not.toHaveProperty('content');
  });

  it('edits one field without losing unknown values or timestamp precision', async () => {
    renderWithProviders(<HarnessEditor kind="skill" item={item} />);
    fireEvent.change(await screen.findByLabelText('Instructions'), {
      target: { value: 'Updated complete instructions.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Skill' }));
    await waitFor(() => expect(api.harness.editor.update).toHaveBeenCalled());
    expect(api.harness.editor.update).toHaveBeenCalledWith(
      'skill',
      1,
      expect.objectContaining({
        expected_version: 3,
        expected_updated_at: '2026-11-05T12:00:00.123456Z',
        dirty_paths: ['/fields/instructions'],
        extensions: draft.extensions,
        original_content: item.content,
      }),
    );
  });

  it('saves an unchanged document with no dirty fields', async () => {
    renderWithProviders(<HarnessEditor kind="skill" item={item} />);
    await screen.findByLabelText('Instructions');
    fireEvent.click(screen.getByRole('button', { name: 'Save Skill' }));
    await waitFor(() => expect(api.harness.editor.update).toHaveBeenCalled());
    expect(api.harness.editor.update).toHaveBeenCalledWith(
      'skill',
      1,
      expect.objectContaining({
        dirty_paths: [],
        original_content: item.content,
      }),
    );
  });

  it('retains invalid Raw input and errors when conversion is refused', async () => {
    renderWithProviders(<HarnessEditor kind="skill" item={item} />);
    await screen.findByLabelText('Instructions');
    fireEvent.click(screen.getByRole('tab', { name: 'Raw' }));
    const raw = await screen.findByLabelText('Raw definition');
    fireEvent.change(raw, { target: { value: '---\ninvalid: [draft' } });
    vi.mocked(api.harness.editor.preview).mockRejectedValueOnce(
      new ApiError('raw.frontmatter contains invalid YAML', 422),
    );
    fireEvent.click(screen.getByRole('tab', { name: 'Guided' }));
    await screen.findByRole('alert');
    expect(screen.getByLabelText('Raw definition')).toHaveValue(
      '---\ninvalid: [draft',
    );
    expect(screen.getByRole('tab', { name: 'Raw' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('ignores a preview captured before the user changes their draft', async () => {
    renderWithProviders(<HarnessEditor kind="skill" item={item} />);
    await screen.findByLabelText('Instructions');
    let finish!: (value: {
      content: HarnessItem['content'];
      draft: HarnessDraft;
    }) => void;
    vi.mocked(api.harness.editor.preview).mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    fireEvent.click(screen.getByRole('tab', { name: 'Raw' }));
    expect(api.harness.editor.preview).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText('Instructions'), {
      target: { value: 'A newer unsaved draft.' },
    });
    await act(async () => {
      finish({ content: item.content, draft });
    });
    expect(screen.getByLabelText('Instructions')).toHaveValue(
      'A newer unsaved draft.',
    );
    expect(screen.getByRole('tab', { name: 'Guided' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('retains the draft on a write conflict and never retries automatically', async () => {
    vi.mocked(api.harness.editor.update).mockRejectedValueOnce(
      new ApiError('This item changed. Reload before saving.', 409),
    );
    renderWithProviders(<HarnessEditor kind="skill" item={item} />);
    fireEvent.change(await screen.findByLabelText('Instructions'), {
      target: { value: 'My retained draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Skill' }));
    await screen.findByRole('alert');
    expect(screen.getByLabelText('Instructions')).toHaveValue(
      'My retained draft.',
    );
    expect(api.harness.editor.update).toHaveBeenCalledTimes(1);
  });

  it('preserves unsupported legacy content in Raw with an explicit guided limitation', async () => {
    vi.mocked(api.harness.editor.decode).mockResolvedValueOnce({
      ...draft,
      fields: {},
      extensions: {},
      capabilities: {
        guided_supported: false,
        unsupported_paths: ['/content/body/frontmatter'],
      },
    });
    renderWithProviders(<HarnessEditor kind="skill" item={item} />);
    expect(await screen.findByLabelText('Raw definition')).toHaveValue(
      item.content!.body,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('frontmatter');
    expect(screen.getByRole('tab', { name: 'Guided' })).toBeDisabled();
  });

  it('does not finalize a save after unmounting', async () => {
    const saved = vi.fn();
    let finish!: (value: HarnessItem) => void;
    vi.mocked(api.harness.editor.update).mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const view = renderWithProviders(
      <HarnessEditor kind="skill" item={item} onSaved={saved} />,
    );
    await screen.findByLabelText('Instructions');
    fireEvent.click(screen.getByRole('button', { name: 'Save Skill' }));
    fireEvent.click(screen.getByRole('button', { name: 'Saving...' }));
    expect(api.harness.editor.update).toHaveBeenCalledTimes(1);
    view.unmount();
    await act(async () => {
      finish(item);
    });
    expect(saved).not.toHaveBeenCalled();
  });
});
