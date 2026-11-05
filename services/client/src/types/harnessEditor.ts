import type { HarnessItem } from '../api';

export type JsonValue =
  string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface FieldDescriptor {
  key: string;
  label: string;
  kind: string;
  placeholder: string;
  required?: boolean;
  default?: JsonValue;
  max_length?: number;
  minimum?: number;
  choices?: string[];
  fields?: FieldDescriptor[];
  create_only?: boolean;
  when?: Record<string, string | string[]>;
}

export interface EditorDescriptors {
  common: FieldDescriptor[];
  types: Record<
    string,
    {
      label: string;
      fields: FieldDescriptor[];
      initial_extensions: JsonObject;
      common_fields?: FieldDescriptor[];
    }
  >;
}

export interface HarnessDraft {
  fields: JsonObject;
  extensions: JsonObject;
  original_content: HarnessItem['content'];
  raw: string;
  capabilities: { guided_supported: boolean; unsupported_paths: string[] };
  diagnostics?: { path: string; message: string }[];
}

export interface HarnessEditorPayload {
  common: JsonObject;
  mode: 'guided' | 'raw';
  fields: JsonObject;
  extensions: JsonObject;
  original_content?: HarnessItem['content'];
  source_name?: string;
  dirty_paths: string[];
  raw?: string;
  expected_version?: number;
  expected_updated_at?: string;
}
