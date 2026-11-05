import { useEffect, useId, useState } from 'react';
import type {
  FieldDescriptor,
  JsonObject,
  JsonValue,
} from '../types/harnessEditor';

export type { FieldDescriptor, JsonValue } from '../types/harnessEditor';

interface FieldsProps {
  fields: FieldDescriptor[];
  values: JsonObject;
  onChange: (key: string, value: JsonValue) => void;
  disabled?: boolean;
  errors?: Record<string, string>;
}

function objectValue(value: JsonValue | undefined): JsonObject {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value
    : {};
}

function defaultValue(field: FieldDescriptor): JsonValue {
  if (field.default !== undefined) return field.default;
  if (field.kind === 'boolean') return false;
  if (['strings', 'rows', 'pairs', 'multiselect'].includes(field.kind))
    return [];
  return '';
}

function errorFor(errors: Record<string, string>, key: string) {
  return (
    errors[key] ||
    errors[`fields.${key}`] ||
    errors[`common.${key}`] ||
    errors[`/fields/${key.replaceAll('.', '/')}`]
  );
}

export function HarnessEditorFields({
  fields,
  values,
  onChange,
  disabled = false,
  errors = {},
}: FieldsProps) {
  return (
    <fieldset
      disabled={disabled}
      style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
    >
      {fields
        .filter(
          (field) =>
            !field.when ||
            Object.entries(field.when).every(([key, expected]) =>
              (Array.isArray(expected) ? expected : [expected]).includes(
                String(values[key] ?? ''),
              ),
            ),
        )
        .map((field) => (
          <DescriptorField
            key={field.key}
            field={field}
            value={
              Object.hasOwn(values, field.key)
                ? values[field.key]
                : defaultValue(field)
            }
            onChange={(value) => onChange(field.key, value)}
            disabled={disabled}
            error={errorFor(errors, field.key)}
            errors={errors}
          />
        ))}
    </fieldset>
  );
}

function DescriptorField({
  field,
  value,
  onChange,
  disabled,
  error,
  errors,
}: {
  field: FieldDescriptor;
  value: JsonValue;
  onChange: (value: JsonValue) => void;
  disabled: boolean;
  error?: string;
  errors: Record<string, string>;
}) {
  const id = useId();
  const feedback = error ? (
    <p id={`${id}-error`} className="text-danger" role="alert">
      {error}
    </p>
  ) : null;
  const inputProps = {
    id,
    disabled,
    'aria-invalid': error ? (true as const) : undefined,
    'aria-describedby': error ? `${id}-error` : undefined,
  };
  const label = (
    <label htmlFor={id} className="form-label">
      {field.label}
    </label>
  );
  const items = Array.isArray(value) ? value : [];
  const replaceRow = (index: number, next: JsonValue) =>
    onChange(items.map((item, position) => (position === index ? next : item)));
  const removeRow = (index: number) =>
    onChange(items.filter((_, position) => position !== index));

  if (field.kind === 'boolean')
    return (
      <div className="form-group">
        <label htmlFor={id}>
          <input
            {...inputProps}
            type="checkbox"
            className="form-checkbox"
            checked={value === true}
            onChange={(event) => onChange(event.target.checked)}
          />{' '}
          {field.label}
        </label>
        {feedback}
      </div>
    );
  if (field.kind === 'multiselect')
    return (
      <fieldset
        className="form-group"
        disabled={disabled}
        aria-describedby={error ? `${id}-error` : undefined}
      >
        <legend className="form-label">{field.label}</legend>
        {(field.choices || []).map((choice) => (
          <label
            key={choice}
            style={{ display: 'inline-flex', gap: 6, marginRight: 16 }}
          >
            <input
              type="checkbox"
              className="form-checkbox"
              checked={items.includes(choice)}
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? [...items, choice]
                    : items.filter((item) => item !== choice),
                )
              }
            />
            {choice}
          </label>
        ))}
        {feedback}
      </fieldset>
    );
  if (['strings', 'rows', 'pairs'].includes(field.kind)) {
    const rowFields =
      field.kind === 'pairs'
        ? ([
            {
              key: 'key',
              label: 'Key',
              kind: 'text',
              placeholder: 'VARIABLE_NAME',
              required: true,
            },
            {
              key: 'value',
              label: 'Value',
              kind: 'text',
              placeholder: field.placeholder,
            },
          ] satisfies FieldDescriptor[])
        : field.fields || [];
    const add = () =>
      onChange([
        ...items,
        field.kind === 'strings'
          ? ''
          : Object.fromEntries(
              rowFields.map((child) => [child.key, defaultValue(child)]),
            ),
      ]);
    return (
      <fieldset
        className="form-group"
        disabled={disabled}
        aria-describedby={error ? `${id}-error` : undefined}
      >
        <legend className="form-label">{field.label}</legend>
        {items.map((item, index) => (
          <div key={index} className="card" style={{ marginBottom: 8 }}>
            {field.kind === 'strings' ? (
              <>
                <label className="form-label" htmlFor={`${id}-${index}`}>
                  {field.label} {index + 1}
                </label>
                <input
                  className="input"
                  id={`${id}-${index}`}
                  value={String(item ?? '')}
                  placeholder={field.placeholder}
                  onChange={(event) => replaceRow(index, event.target.value)}
                />
              </>
            ) : field.kind === 'pairs' ? (
              <div className="form-grid">
                {rowFields.map((child) => (
                  <div key={child.key}>
                    <label
                      className="form-label"
                      htmlFor={`${id}-${index}-${child.key}`}
                    >
                      {child.label} {index + 1}
                    </label>
                    <input
                      className="input"
                      id={`${id}-${index}-${child.key}`}
                      value={String(objectValue(item)[child.key] ?? '')}
                      placeholder={child.placeholder}
                      required={child.required}
                      onChange={(event) =>
                        replaceRow(index, {
                          ...objectValue(item),
                          [child.key]: event.target.value,
                        })
                      }
                    />
                  </div>
                ))}
              </div>
            ) : (
              <HarnessEditorFields
                fields={rowFields}
                values={objectValue(item)}
                disabled={disabled}
                errors={Object.fromEntries(
                  Object.entries(errors)
                    .filter(([key]) => key.startsWith(`${field.key}.${index}.`))
                    .map(([key, message]) => [
                      key.slice(`${field.key}.${index}.`.length),
                      message,
                    ]),
                )}
                onChange={(key, next) =>
                  replaceRow(index, { ...objectValue(item), [key]: next })
                }
              />
            )}
            <button
              type="button"
              className="btn btn-sm"
              aria-label={`Remove ${field.kind === 'strings' ? 'value' : 'row'} ${index + 1}`}
              onClick={() => removeRow(index)}
            >
              Remove
            </button>
          </div>
        ))}
        <button type="button" className="btn btn-sm" onClick={add}>
          {field.kind === 'strings' ? 'Add value' : 'Add row'}
        </button>
        {feedback}
      </fieldset>
    );
  }
  if (field.kind === 'select')
    return (
      <div className="form-group">
        {label}
        <select
          {...inputProps}
          className="input"
          required={field.required}
          value={String(value ?? '')}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">{field.placeholder}</option>
          {(field.choices || []).map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
          {typeof value === 'string' &&
            value &&
            !field.choices?.includes(value) && (
              <option value={value}>{value}</option>
            )}
        </select>
        {feedback}
      </div>
    );
  if (field.kind === 'markdown')
    return (
      <div className="form-group">
        {label}
        <textarea
          {...inputProps}
          className="input"
          rows={8}
          value={String(value ?? '')}
          placeholder={field.placeholder}
          required={field.required}
          maxLength={field.max_length}
          onChange={(event) => onChange(event.target.value)}
        />
        {feedback}
      </div>
    );
  if (field.kind === 'number')
    return (
      <div className="form-group">
        {label}
        <input
          {...inputProps}
          className="input"
          type="number"
          step="any"
          min={field.minimum}
          value={value === null ? '' : String(value)}
          placeholder={field.placeholder}
          required={field.required}
          onChange={(event) =>
            onChange(
              event.target.value === '' ? '' : Number(event.target.value),
            )
          }
        />
        {feedback}
      </div>
    );
  if (field.kind !== 'text')
    return (
      <JsonValueEditor
        label={field.label}
        value={value}
        onChange={onChange}
        disabled={disabled}
      />
    );
  return (
    <div className="form-group">
      {label}
      <input
        {...inputProps}
        className="input"
        value={String(value ?? '')}
        placeholder={field.placeholder}
        required={field.required}
        maxLength={field.max_length}
        onChange={(event) => onChange(event.target.value)}
      />
      {feedback}
    </div>
  );
}

type ValueKind = 'string' | 'number' | 'boolean' | 'null' | 'array' | 'object';
const VALUE_TYPES: { value: ValueKind; label: string; initial: JsonValue }[] = [
  { value: 'string', label: 'Text', initial: '' },
  { value: 'number', label: 'Number', initial: 0 },
  { value: 'boolean', label: 'True / false', initial: false },
  { value: 'null', label: 'Empty value', initial: null },
  { value: 'array', label: 'List', initial: [] },
  { value: 'object', label: 'Group', initial: {} },
];
function valueKind(value: JsonValue): ValueKind {
  return value === null
    ? 'null'
    : Array.isArray(value)
      ? 'array'
      : (typeof value as ValueKind);
}
function initialValue(type: string) {
  const option = VALUE_TYPES.find((candidate) => candidate.value === type);
  return structuredClone(option ? option.initial : '');
}

function JsonNumberInput({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  const [error, setError] = useState('');
  useEffect(() => {
    setDraft(String(value));
  }, [value]);
  return (
    <>
      <label className="form-label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="input"
        type="number"
        step="any"
        required
        value={draft}
        placeholder="10"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event) => {
          const text = event.target.value;
          setDraft(text);
          const message =
            text !== '' && Number.isFinite(Number(text))
              ? ''
              : 'Enter a finite number or choose Empty value.';
          setError(message);
          event.target.setCustomValidity(message);
          if (!message) onChange(Number(text));
        }}
      />
      {error && (
        <p id={`${id}-error`} role="alert">
          {error}
        </p>
      )}
    </>
  );
}

export function JsonValueEditor({
  label,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  value: JsonValue;
  onChange: (value: JsonValue) => void;
  disabled?: boolean;
  path?: string;
}) {
  const id = useId();
  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState('string');
  const [error, setError] = useState('');
  const kind = valueKind(value);
  const mapping = objectValue(value);
  const addField = () => {
    if (!newName.trim()) {
      setError('Enter a field name.');
      return;
    }
    if (Object.hasOwn(mapping, newName)) {
      setError('That field name already exists.');
      return;
    }
    onChange({ ...mapping, [newName]: initialValue(newType) });
    setNewName('');
    setError('');
  };
  return (
    <fieldset
      className="form-group"
      disabled={disabled}
      style={{ minWidth: 0 }}
    >
      <legend className="form-label">{label}</legend>
      <label className="form-label" htmlFor={`${id}-type`}>
        {label} type
      </label>
      <select
        id={`${id}-type`}
        className="input"
        value={kind}
        onChange={(event) => onChange(initialValue(event.target.value))}
      >
        {VALUE_TYPES.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {kind === 'string' && (
        <>
          <label className="form-label" htmlFor={`${id}-value`}>
            {label}
          </label>
          <textarea
            id={`${id}-value`}
            className="input"
            rows={String(value).includes('\n') ? 4 : 1}
            value={String(value)}
            placeholder="Example setting value"
            onChange={(event) => onChange(event.target.value)}
          />
        </>
      )}
      {kind === 'number' && (
        <JsonNumberInput
          id={`${id}-value`}
          label={label}
          value={value as number}
          onChange={onChange}
        />
      )}
      {kind === 'boolean' && (
        <label htmlFor={`${id}-value`}>
          <input
            id={`${id}-value`}
            type="checkbox"
            className="form-checkbox"
            checked={value === true}
            onChange={(event) => onChange(event.target.checked)}
          />{' '}
          {label}
        </label>
      )}
      {kind === 'object' && (
        <>
          {Object.entries(mapping).map(([key, child]) => (
            <div className="card" key={key} style={{ marginTop: 8 }}>
              <JsonValueEditor
                label={key}
                value={child}
                disabled={disabled}
                onChange={(next) => onChange({ ...mapping, [key]: next })}
              />
              <button
                type="button"
                className="btn btn-sm"
                aria-label={`Remove field ${key}`}
                onClick={() => {
                  const next = { ...mapping };
                  delete next[key];
                  onChange(next);
                }}
              >
                Remove field
              </button>
            </div>
          ))}
          <div className="form-grid">
            <div>
              <label className="form-label" htmlFor={`${id}-name`}>
                New field name for {label}
              </label>
              <input
                id={`${id}-name`}
                className="input"
                placeholder="custom_setting"
                value={newName}
                onChange={(event) => {
                  setNewName(event.target.value);
                  setError('');
                }}
              />
            </div>
            <div>
              <label className="form-label" htmlFor={`${id}-new-type`}>
                New field type for {label}
              </label>
              <select
                id={`${id}-new-type`}
                className="input"
                value={newType}
                onChange={(event) => setNewType(event.target.value)}
              >
                {VALUE_TYPES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button
            type="button"
            className="btn btn-sm"
            aria-label={`Add field to ${label}`}
            onClick={addField}
          >
            Add field
          </button>
          {error && <p role="alert">{error}</p>}
        </>
      )}
      {kind === 'array' && (
        <>
          {(value as JsonValue[]).map((child, index) => (
            <div className="card" key={index} style={{ marginTop: 8 }}>
              <JsonValueEditor
                label={`${label} item ${index + 1}`}
                value={child}
                disabled={disabled}
                onChange={(next) =>
                  onChange(
                    (value as JsonValue[]).map((item, position) =>
                      position === index ? next : item,
                    ),
                  )
                }
              />
              <button
                type="button"
                className="btn btn-sm"
                aria-label={`Remove item ${index + 1} from ${label}`}
                onClick={() =>
                  onChange(
                    (value as JsonValue[]).filter(
                      (_, position) => position !== index,
                    ),
                  )
                }
              >
                Remove item
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn btn-sm"
            aria-label={`Add item to ${label}`}
            onClick={() => onChange([...(value as JsonValue[]), ''])}
          >
            Add item
          </button>
        </>
      )}
    </fieldset>
  );
}
