/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { URL as FileURL, fileURLToPath } from 'node:url';
import type { HarnessItem } from '../../api';
import type {
  EditorDescriptors,
  HarnessDraft,
  JsonObject,
  JsonValue,
} from '../../types/harnessEditor';

export type HarnessKind = 'rule' | 'skill' | 'tool' | 'hook' | 'agent';
export interface HarnessEditorCase {
  common: JsonObject;
  fields: JsonObject;
  extensions: JsonObject;
  item: HarnessItem;
  draft: HarnessDraft;
  changed_field: string;
  updated_value: JsonValue;
  updated: HarnessItem;
  updated_draft: HarnessDraft;
}
export const editorFixtures = JSON.parse(
  readFileSync(
    fileURLToPath(
      new FileURL(
        '../../../../../tests/fixtures/harness_editor_types.json',
        import.meta.url,
      ),
    ),
    'utf8',
  ),
) as {
  descriptors: EditorDescriptors;
  cases: Record<HarnessKind, HarnessEditorCase>;
};
export const harnessKinds: HarnessKind[] = [
  'rule',
  'skill',
  'tool',
  'hook',
  'agent',
];
