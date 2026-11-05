import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { api, type HarnessItem } from '../api';
import { formatError } from '../constants';
import { useApiRead } from '../hooks/useApiRead';
import { usePageLifetime } from '../hooks/usePageLifetime';
import type {
  FieldDescriptor,
  HarnessDraft,
  HarnessEditorPayload,
  JsonObject,
  JsonValue,
} from '../types/harnessEditor';
import { HarnessEditorFields, JsonValueEditor } from './HarnessEditorFields';

interface DraftState {
  common: JsonObject;
  fields: JsonObject;
  extensions: JsonObject;
  raw: string;
  mode: 'guided' | 'raw';
}

const copy = <T,>(value: T): T => structuredClone(value);
const defaults = (fields: FieldDescriptor[]): JsonObject =>
  Object.fromEntries(
    fields.map((field) => [field.key, copy(field.default ?? '')]),
  );
const pointer = (key: string) => key.replace(/~/g, '~0').replace(/\//g, '~1');

function changedPaths(
  before: JsonValue,
  after: JsonValue,
  path = '',
): string[] {
  if (JSON.stringify(before) === JSON.stringify(after)) return [];
  if (
    before &&
    after &&
    typeof before === 'object' &&
    typeof after === 'object' &&
    !Array.isArray(before) &&
    !Array.isArray(after)
  ) {
    return [
      ...new Set([...Object.keys(before), ...Object.keys(after)]),
    ].flatMap((key) =>
      key in before && key in after
        ? changedPaths(before[key], after[key], `${path}/${pointer(key)}`)
        : [`${path}/${pointer(key)}`],
    );
  }
  return [path];
}

export function HarnessEditor({
  kind,
  item,
  onSaved,
  onCancel,
}: {
  kind: string;
  item?: HarnessItem;
  onSaved?: (saved: HarnessItem) => void;
  onCancel?: () => void;
}) {
  const navigate = useNavigate();
  const isCurrent = usePageLifetime();
  const id = useId();
  const [source] = useState(item);
  const load = useCallback(async () => {
    const definitions = await api.harness.editor.descriptors();
    const definition = definitions.types[kind];
    if (!definition) throw new Error('This harness type has no guided editor.');
    const baseline: HarnessDraft = source
      ? await api.harness.editor.decode(kind, source.name, source.content)
      : {
          fields: defaults(definition.fields),
          extensions: copy(definition.initial_extensions),
          original_content: undefined,
          raw: '',
          capabilities: { guided_supported: true, unsupported_paths: [] },
        };
    return { definitions, baseline };
  }, [kind, source]);
  const read = useApiRead(load);
  const [draft, setDraft] = useState<DraftState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const writing = useRef(false);
  const previewRequest = useRef(0);
  const revision = useRef(0);

  useEffect(() => {
    if (!read.data || draft) return;
    const { definitions, baseline } = read.data;
    const commonDescriptors = [
      ...definitions.common,
      ...(definitions.types[kind].common_fields ?? []),
    ];
    const common = defaults(commonDescriptors);
    if (source) {
      const saved = source as unknown as JsonObject;
      for (const field of commonDescriptors)
        if (saved[field.key] !== undefined)
          common[field.key] = copy(saved[field.key]);
    }
    setDraft({
      common,
      fields: copy(baseline.fields),
      extensions: copy(baseline.extensions),
      raw: baseline.raw,
      mode: baseline.capabilities.guided_supported ? 'guided' : 'raw',
    });
  }, [read.data, draft, source, kind]);

  const change = (
    section: 'common' | 'fields',
    key: string,
    value: JsonValue,
  ) => {
    revision.current += 1;
    setError(null);
    setDraft((current) =>
      current
        ? { ...current, [section]: { ...current[section], [key]: value } }
        : current,
    );
  };

  function payload(current: DraftState): HarnessEditorPayload {
    const baseline = read.data!.baseline;
    return {
      common: {
        ...copy(current.common),
        project: current.common.project || null,
      },
      mode: current.mode,
      fields: copy(current.fields),
      extensions: copy(current.extensions),
      raw: current.raw,
      original_content: baseline.original_content,
      source_name: source?.name,
      dirty_paths: changedPaths(
        { fields: baseline.fields, extensions: baseline.extensions },
        { fields: current.fields, extensions: current.extensions },
      ),
      ...(source
        ? {
            expected_version: source.version,
            expected_updated_at: source.updated_at,
          }
        : {}),
    };
  }

  async function switchMode(mode: 'guided' | 'raw') {
    if (!draft || draft.mode === mode || previewing || writing.current) return;
    const captured = revision.current;
    const requestId = ++previewRequest.current;
    setError(null);
    setPreviewing(true);
    try {
      const response = await api.harness.editor.preview(kind, payload(draft));
      if (
        !isCurrent() ||
        requestId !== previewRequest.current ||
        revision.current !== captured
      )
        return;
      if (mode === 'guided' && !response.draft.capabilities.guided_supported) {
        setError(
          `Guided editing cannot preserve ${response.draft.capabilities.unsupported_paths.join(', ')}. Your Raw draft is retained.`,
        );
        return;
      }
      setDraft((current) =>
        current
          ? {
              ...current,
              mode,
              raw: response.draft.raw,
              ...(mode === 'guided'
                ? {
                    fields: response.draft.fields,
                    extensions: response.draft.extensions,
                  }
                : {}),
            }
          : current,
      );
    } catch (failure) {
      if (
        isCurrent() &&
        requestId === previewRequest.current &&
        revision.current === captured
      )
        setError(formatError(failure));
    } finally {
      if (isCurrent() && requestId === previewRequest.current)
        setPreviewing(false);
    }
  }

  async function save() {
    if (!draft || writing.current || previewing) return;
    const request = payload(draft);
    writing.current = true;
    setSaving(true);
    setError(null);
    try {
      const saved = source
        ? await api.harness.editor.update(kind, source.id, request)
        : await api.harness.editor.create(kind, request);
      if (!isCurrent()) return;
      if (onSaved) onSaved(saved);
      else
        navigate(`/harness/${kind}/${saved.id}`, { replace: Boolean(source) });
    } catch (failure) {
      if (isCurrent()) setError(formatError(failure));
    } finally {
      writing.current = false;
      if (isCurrent()) setSaving(false);
    }
  }

  if (read.error)
    return (
      <div role="alert" className="card">
        Could not load editor.{' '}
        <button className="btn" onClick={() => read.refresh()}>
          Retry
        </button>
      </div>
    );
  if (!draft || !read.data) return <p className="loading">Loading editor...</p>;
  const { definitions, baseline } = read.data;
  const definition = definitions.types[kind];
  const commonFields = [
    ...definitions.common,
    ...(definition.common_fields ?? []),
  ].filter((field) => !source || !field.create_only);
  const fieldErrors: Record<string, string> = {};
  const match = error?.match(/^(?:fields|common)\.([a-zA-Z_][\w]*)/);
  if (match && error) fieldErrors[match[1]] = error;
  const commonError = error?.match(/^([a-zA-Z_][\w]*):/);
  if (
    commonError &&
    error &&
    commonFields.some((field) => field.key === commonError[1])
  )
    fieldErrors[commonError[1]] = error;

  return (
    <form
      className="harness-editor"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <h2 className="page-title">
        {source ? 'Edit' : 'New'} {definition.label}
      </h2>
      <section className="card" aria-label="Identity and availability">
        <h3 className="section-title">Identity and availability</h3>
        <HarnessEditorFields
          fields={commonFields}
          values={draft.common}
          onChange={(key, value) => change('common', key, value)}
          disabled={saving}
          errors={fieldErrors}
        />
      </section>
      <div
        className="resource-tabs"
        role="tablist"
        aria-label="Definition editor"
      >
        <button
          type="button"
          role="tab"
          aria-selected={draft.mode === 'guided'}
          aria-controls={`${id}-guided`}
          disabled={
            saving || previewing || !baseline.capabilities.guided_supported
          }
          onClick={() => {
            void switchMode('guided');
          }}
        >
          Guided
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={draft.mode === 'raw'}
          aria-controls={`${id}-raw`}
          disabled={saving || previewing}
          onClick={() => {
            void switchMode('raw');
          }}
        >
          Raw
        </button>
      </div>
      {!baseline.capabilities.guided_supported && (
        <p className="card" role="alert">
          Guided editing cannot preserve{' '}
          {baseline.diagnostics
            ?.map((diagnostic) => diagnostic.message)
            .join('; ') || baseline.capabilities.unsupported_paths.join(', ')}
          . The original Raw definition remains intact.
        </p>
      )}
      {error && (
        <p className="card" role="alert">
          {error}
        </p>
      )}
      {previewing && <p role="status">Preparing the other view...</p>}
      {draft.mode === 'guided' ? (
        <section
          className="card"
          id={`${id}-guided`}
          role="tabpanel"
          aria-label="Guided definition"
        >
          <HarnessEditorFields
            fields={definition.fields}
            values={{ ...draft.common, ...draft.fields }}
            onChange={(key, value) => change('fields', key, value)}
            disabled={saving}
            errors={fieldErrors}
          />
          <JsonValueEditor
            label="Additional settings"
            value={draft.extensions}
            disabled={saving}
            onChange={(value) => {
              if (
                value === null ||
                typeof value !== 'object' ||
                Array.isArray(value)
              )
                return;
              revision.current += 1;
              setError(null);
              setDraft((current) =>
                current ? { ...current, extensions: value } : current,
              );
            }}
          />
        </section>
      ) : (
        <section
          className="card"
          id={`${id}-raw`}
          role="tabpanel"
          aria-label="Raw definition editor"
        >
          <label className="form-label" htmlFor={`${id}-raw-input`}>
            Raw definition
          </label>
          <textarea
            className="input"
            id={`${id}-raw-input`}
            rows={18}
            value={draft.raw}
            disabled={saving}
            spellCheck={false}
            placeholder="The backend assembles this definition from the Guided fields."
            onChange={(event) => {
              revision.current += 1;
              setError(null);
              setDraft((current) =>
                current ? { ...current, raw: event.target.value } : current,
              );
            }}
          />
        </section>
      )}
      <div className="flex-wrap">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={saving || previewing}
        >
          {saving
            ? 'Saving...'
            : `${source ? 'Save' : 'Create'} ${definition.label}`}
        </button>
        <button
          type="button"
          className="btn"
          disabled={saving}
          onClick={() => {
            if (onCancel) onCancel();
            else navigate(`/harness/${kind}s`);
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
