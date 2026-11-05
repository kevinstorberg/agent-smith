import { readFileSync } from 'node:fs';
import type { Locator, Page } from '@playwright/test';
import type {
  EditorDescriptors,
  FieldDescriptor,
  JsonObject,
  JsonValue,
} from '../src/types/harnessEditor';
import type {
  HarnessEditorCase,
  HarnessKind,
} from '../src/pages/__tests__/harnessEditorFixtures';

export const harnessEditorFixture = JSON.parse(
  readFileSync(
    new URL(
      '../../../tests/fixtures/harness_editor_types.json',
      import.meta.url,
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

type Scope = Page | Locator;
const kindOf = (value: JsonValue) =>
  value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value;

export async function fillJsonValue(
  scope: Scope,
  label: string,
  value: JsonValue,
) {
  const group = scope.getByRole('group', { name: label, exact: true });
  await group
    .getByLabel(`${label} type`, { exact: true })
    .selectOption({ value: kindOf(value) });
  if (Array.isArray(value)) {
    for (const [index, child] of value.entries()) {
      await group
        .getByRole('button', { name: `Add item to ${label}`, exact: true })
        .click();
      await fillJsonValue(group, `${label} item ${index + 1}`, child);
    }
  } else if (value !== null && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      if (
        (await group.getByRole('group', { name: key, exact: true }).count()) ===
        0
      ) {
        await group
          .getByLabel(`New field name for ${label}`, { exact: true })
          .fill(key);
        await group
          .getByLabel(`New field type for ${label}`, { exact: true })
          .selectOption({ value: kindOf(child) });
        await group
          .getByRole('button', { name: `Add field to ${label}`, exact: true })
          .click();
      }
      await fillJsonValue(group, key, child);
    }
  } else if (typeof value === 'boolean') {
    await group.getByLabel(label, { exact: true }).setChecked(value);
  } else if (value !== null) {
    await group.getByLabel(label, { exact: true }).fill(String(value));
  }
}

export async function fillHarnessFields(
  scope: Scope,
  descriptors: FieldDescriptor[],
  values: JsonObject,
  context: JsonObject = values,
) {
  for (const field of descriptors) {
    if (
      !(field.key in values) ||
      (field.when &&
        !Object.entries(field.when).every(([key, expected]) =>
          (Array.isArray(expected) ? expected : [expected]).includes(
            String(context[key] ?? ''),
          ),
        ))
    )
      continue;
    const value = values[field.key];
    if (field.kind === 'boolean')
      await scope
        .getByLabel(field.label, { exact: true })
        .setChecked(value === true);
    else if (field.kind === 'select')
      await scope
        .getByLabel(field.label, { exact: true })
        .selectOption({ value: String(value) });
    else if (field.kind === 'multiselect') {
      const group = scope.getByRole('group', {
        name: field.label,
        exact: true,
      });
      for (const choice of field.choices ?? [])
        await group
          .getByLabel(choice, { exact: true })
          .setChecked(Array.isArray(value) && value.includes(choice));
    } else if (['rows', 'pairs', 'strings'].includes(field.kind)) {
      const group = scope.getByRole('group', {
        name: field.label,
        exact: true,
      });
      for (const [index, row] of (value as JsonValue[]).entries()) {
        await group
          .getByRole('button', {
            name: field.kind === 'strings' ? 'Add value' : 'Add row',
            exact: true,
          })
          .click();
        if (field.kind === 'strings')
          await group
            .getByLabel(`${field.label} ${index + 1}`, { exact: true })
            .fill(String(row));
        else if (field.kind === 'pairs') {
          await group
            .getByLabel(`Key ${index + 1}`, { exact: true })
            .fill(String((row as JsonObject).key));
          await group
            .getByLabel(`Value ${index + 1}`, { exact: true })
            .fill(String((row as JsonObject).value));
        } else
          await fillHarnessFields(
            group.locator(':scope > .card').nth(index),
            field.fields ?? [],
            row as JsonObject,
          );
      }
    } else if (field.kind === 'json')
      await fillJsonValue(scope, field.label, value);
    else
      await scope
        .getByLabel(field.label, { exact: true })
        .fill(String(value ?? ''));
  }
}

export async function fillHarnessExample(page: Page, kind: HarnessKind) {
  const example = harnessEditorFixture.cases[kind];
  const definition = harnessEditorFixture.descriptors.types[kind];
  await fillHarnessFields(
    page,
    [
      ...harnessEditorFixture.descriptors.common,
      ...(definition.common_fields ?? []),
    ],
    example.common,
  );
  await fillHarnessFields(page, definition.fields, example.fields, {
    ...example.common,
    ...example.fields,
  });
  await fillJsonValue(page, 'Additional settings', example.extensions);
}
