import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { HarnessEditorFields, JsonValueEditor } from '../HarnessEditorFields';
import type {
  FieldDescriptor,
  JsonObject,
  JsonValue,
} from '../../types/harnessEditor';

function Fields({
  descriptors,
  initial,
  disabled = false,
  errors = {},
}: {
  descriptors: FieldDescriptor[];
  initial: JsonObject;
  disabled?: boolean;
  errors?: Record<string, string>;
}) {
  const [values, setValues] = useState(initial);
  return (
    <>
      <HarnessEditorFields
        fields={descriptors}
        values={values}
        disabled={disabled}
        errors={errors}
        onChange={(key, value) =>
          setValues((current) => ({ ...current, [key]: value }))
        }
      />
      <output data-testid="values">{JSON.stringify(values)}</output>
    </>
  );
}

function Extensions({ initial }: { initial: JsonValue }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <JsonValueEditor
        label="Additional settings"
        value={value}
        onChange={setValue}
      />
      <output data-testid="values">{JSON.stringify(value)}</output>
    </>
  );
}

const description: FieldDescriptor = {
  key: 'description',
  label: 'Description / when to use',
  kind: 'text',
  placeholder: 'Use when reviewing changes.',
  required: true,
  max_length: 80,
};

describe('HarnessEditorFields', () => {
  it('edits descriptor-based nested JSON settings without raw structure', () => {
    render(
      <Fields
        descriptors={[
          {
            key: 'settings',
            label: 'Additional handler settings',
            kind: 'json',
            placeholder: 'Add a handler setting',
          },
        ]}
        initial={{
          settings: { retry: 3, nested: { enabled: true }, note: 'keep' },
        }}
      />,
    );
    fireEvent.change(screen.getByRole('spinbutton', { name: 'retry' }), {
      target: { value: '5' },
    });
    expect(JSON.parse(screen.getByTestId('values').textContent!)).toEqual({
      settings: { retry: 5, nested: { enabled: true }, note: 'keep' },
    });
  });

  it('renders independent labeled inputs with server examples and constraints', () => {
    render(
      <Fields
        descriptors={[
          description,
          {
            key: 'instructions',
            label: 'Instructions',
            kind: 'markdown',
            placeholder: 'Read every changed file.',
          },
          {
            key: 'timeout',
            label: 'Timeout',
            kind: 'number',
            placeholder: '30',
            minimum: 1,
          },
        ]}
        initial={{ description: '', instructions: '', timeout: 10 }}
      />,
    );
    expect(
      screen.getByRole('textbox', { name: 'Description / when to use' }),
    ).toHaveAttribute('placeholder', 'Use when reviewing changes.');
    expect(
      screen.getByRole('textbox', { name: 'Description / when to use' }),
    ).toBeRequired();
    expect(
      screen.getByRole('textbox', { name: 'Description / when to use' }),
    ).toHaveAttribute('maxlength', '80');
    expect(
      screen.getByRole('textbox', { name: 'Instructions' }),
    ).toHaveAttribute('placeholder', 'Read every changed file.');
    expect(screen.getByRole('spinbutton', { name: 'Timeout' })).toHaveAttribute(
      'min',
      '1',
    );
    fireEvent.change(
      screen.getByRole('textbox', { name: 'Description / when to use' }),
      { target: { value: 'Use for audits.' } },
    );
    expect(JSON.parse(screen.getByTestId('values').textContent!)).toEqual({
      description: 'Use for audits.',
      instructions: '',
      timeout: 10,
    });
  });

  it('connects precise field errors to their input', () => {
    render(
      <Fields
        descriptors={[description]}
        initial={{ description: '' }}
        errors={{
          description: 'Enter a description explaining when to use this skill.',
        }}
      />,
    );
    expect(
      screen.getByRole('textbox', { name: 'Description / when to use' }),
    ).toHaveAccessibleDescription(
      'Enter a description explaining when to use this skill.',
    );
    expect(
      screen.getByRole('textbox', { name: 'Description / when to use' }),
    ).toHaveAttribute('aria-invalid', 'true');
  });

  it('keeps hidden conditional settings intact when selecting transport', () => {
    render(
      <Fields
        descriptors={[
          {
            key: 'transport',
            label: 'Connection type',
            kind: 'select',
            placeholder: 'Choose a connection',
            choices: ['http', 'stdio'],
          },
          {
            key: 'url',
            label: 'Server URL',
            kind: 'text',
            placeholder: 'https://example.test/mcp',
            when: { transport: 'http' },
          },
          {
            key: 'command',
            label: 'Command',
            kind: 'text',
            placeholder: 'python3',
            when: { transport: 'stdio' },
          },
        ]}
        initial={{
          transport: 'http',
          url: 'https://example.test/mcp',
          command: 'python3',
        }}
      />,
    );
    expect(
      screen.queryByRole('textbox', { name: 'Command' }),
    ).not.toBeInTheDocument();
    fireEvent.change(
      screen.getByRole('combobox', { name: 'Connection type' }),
      { target: { value: 'stdio' } },
    );
    expect(screen.getByRole('textbox', { name: 'Command' })).toHaveValue(
      'python3',
    );
    expect(JSON.parse(screen.getByTestId('values').textContent!).url).toBe(
      'https://example.test/mcp',
    );
  });

  it('edits ordered argument values without entering JSON', () => {
    render(
      <Fields
        descriptors={[
          {
            key: 'args',
            label: 'Arguments',
            kind: 'strings',
            placeholder: '--read-only',
          },
        ]}
        initial={{ args: ['-m'] }}
      />,
    );
    const group = within(screen.getByRole('group', { name: 'Arguments' }));
    fireEvent.click(group.getByRole('button', { name: 'Add value' }));
    const inputs = group.getAllByRole('textbox');
    fireEvent.change(inputs[1], {
      target: { value: 'services.repositories.server' },
    });
    expect(JSON.parse(screen.getByTestId('values').textContent!).args).toEqual([
      '-m',
      'services.repositories.server',
    ]);
    fireEvent.click(group.getByRole('button', { name: 'Remove value 1' }));
    expect(JSON.parse(screen.getByTestId('values').textContent!).args).toEqual([
      'services.repositories.server',
    ]);
  });

  it('edits file and handler rows independently while retaining unknown row fields', () => {
    render(
      <Fields
        descriptors={[
          {
            key: 'files',
            label: 'Supporting files',
            kind: 'rows',
            placeholder: 'references/checklist.md',
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
                placeholder: 'Check the boundaries.',
              },
            ],
          },
        ]}
        initial={{
          files: [{ path: 'references/old.md', content: 'Keep', custom: true }],
        }}
      />,
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'File path' }), {
      target: { value: 'references/new.md' },
    });
    expect(JSON.parse(screen.getByTestId('values').textContent!).files).toEqual(
      [{ path: 'references/new.md', content: 'Keep', custom: true }],
    );
    fireEvent.click(
      within(screen.getByRole('group', { name: 'Supporting files' })).getByRole(
        'button',
        { name: 'Add row' },
      ),
    );
    expect(screen.getAllByRole('textbox', { name: 'File path' })).toHaveLength(
      2,
    );
  });

  it('renders independent key/value rows using the descriptor examples', () => {
    render(
      <Fields
        descriptors={[
          {
            key: 'env',
            label: 'Environment variables',
            kind: 'pairs',
            placeholder: '${API_TOKEN}',
          },
        ]}
        initial={{ env: [{ key: 'API_TOKEN', value: '${API_TOKEN}' }] }}
      />,
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Value 1' }), {
      target: { value: '${OTHER_TOKEN}' },
    });
    expect(screen.getByRole('textbox', { name: 'Value 1' })).toHaveAttribute(
      'placeholder',
      '${API_TOKEN}',
    );
    expect(JSON.parse(screen.getByTestId('values').textContent!).env).toEqual([
      { key: 'API_TOKEN', value: '${OTHER_TOKEN}' },
    ]);
  });

  it('disables all controls during saves', () => {
    const change = vi.fn();
    render(
      <HarnessEditorFields
        fields={[
          description,
          {
            key: 'args',
            label: 'Arguments',
            kind: 'strings',
            placeholder: '-m',
          },
        ]}
        values={{ description: '', args: ['-m'] }}
        disabled
        onChange={change}
      />,
    );
    expect(
      screen.getByRole('textbox', { name: 'Description / when to use' }),
    ).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Add value' })).toBeDisabled();
  });

  it('gives identical labels distinct accessible control IDs across editors', () => {
    render(
      <>
        <Fields
          descriptors={[description]}
          initial={{ description: 'First' }}
        />
        <Fields
          descriptors={[description]}
          initial={{ description: 'Second' }}
        />
      </>,
    );
    const inputs = screen.getAllByRole('textbox', {
      name: 'Description / when to use',
    });
    expect(inputs[0].id).not.toBe(inputs[1].id);
  });
});

describe('JsonValueEditor', () => {
  it('edits nested values while preserving unrelated arrays, nulls and unknown fields', () => {
    render(
      <Extensions
        initial={{
          custom: { policy: 'original', enabled: true },
          keep: [1, null, 'tail'],
        }}
      />,
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'policy' }), {
      target: { value: 'updated' },
    });
    expect(JSON.parse(screen.getByTestId('values').textContent!)).toEqual({
      custom: { policy: 'updated', enabled: true },
      keep: [1, null, 'tail'],
    });
  });

  it('validates duplicate names without overwriting an existing property', () => {
    render(<Extensions initial={{ keep: 'original' }} />);
    fireEvent.change(
      screen.getByRole('textbox', {
        name: 'New field name for Additional settings',
      }),
      { target: { value: 'keep' } },
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Add field to Additional settings' }),
    );
    expect(
      screen.getByText('That field name already exists.'),
    ).toBeInTheDocument();
    expect(JSON.parse(screen.getByTestId('values').textContent!)).toEqual({
      keep: 'original',
    });
  });

  it('adds typed nested groups and values without a JSON textarea', () => {
    render(<Extensions initial={{ keep: true }} />);
    fireEvent.change(
      screen.getByRole('textbox', {
        name: 'New field name for Additional settings',
      }),
      { target: { value: 'settings' } },
    );
    fireEvent.change(
      screen.getByRole('combobox', {
        name: 'New field type for Additional settings',
      }),
      { target: { value: 'object' } },
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Add field to Additional settings' }),
    );
    expect(JSON.parse(screen.getByTestId('values').textContent!)).toEqual({
      keep: true,
      settings: {},
    });
    fireEvent.change(
      screen.getByRole('textbox', { name: 'New field name for settings' }),
      { target: { value: 'note' } },
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Add field to settings' }),
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'note' }), {
      target: { value: 'independent field' },
    });
    expect(JSON.parse(screen.getByTestId('values').textContent!)).toEqual({
      keep: true,
      settings: { note: 'independent field' },
    });
  });

  it('keeps an invalid numeric draft visible and blocks form submission until corrected', () => {
    render(<Extensions initial={{ count: 5 }} />);
    const input = screen.getByRole('spinbutton', { name: 'count' });
    fireEvent.change(input, { target: { value: '' } });
    expect(input).toBeInvalid();
    expect(input).toHaveAccessibleDescription(
      'Enter a finite number or choose Empty value.',
    );
    expect(JSON.parse(screen.getByTestId('values').textContent!)).toEqual({
      count: 5,
    });
    fireEvent.change(input, { target: { value: '12.5' } });
    expect(input).toBeValid();
    expect(JSON.parse(screen.getByTestId('values').textContent!)).toEqual({
      count: 12.5,
    });
  });

  it('preserves multiline extension text and changes null only through its explicit type control', () => {
    render(<Extensions initial={{ note: 'first\nsecond', optional: null }} />);
    expect(screen.getByRole('textbox', { name: 'note' })).toHaveValue(
      'first\nsecond',
    );
    fireEvent.change(screen.getByRole('combobox', { name: 'optional type' }), {
      target: { value: 'boolean' },
    });
    expect(JSON.parse(screen.getByTestId('values').textContent!)).toEqual({
      note: 'first\nsecond',
      optional: false,
    });
  });

  it('clears an additional setting to an explicit null value', () => {
    render(<Extensions initial={{ setting: 12 }} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'setting type' }), {
      target: { value: 'null' },
    });
    expect(JSON.parse(screen.getByTestId('values').textContent!)).toEqual({
      setting: null,
    });
  });
});
