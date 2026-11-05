import { readFileSync } from 'node:fs';
import { test, expect, type APIRequest } from './fixtures';
import type { HarnessItem } from '../src/api';
import {
  harnessEditorFixture,
  harnessKinds,
  fillHarnessExample,
} from './harnessEditorFixture';
import {
  expectDocumentContained,
  expectMainContained,
  expectControlsUnclipped,
} from './geometry';
import type {
  EditorDescriptors,
  HarnessDraft,
  HarnessEditorPayload,
} from '../src/types/harnessEditor';

const skill = JSON.parse(
  readFileSync(
    new URL(
      '../../../tests/fixtures/harness_editor_skill.json',
      import.meta.url,
    ),
    'utf8',
  ),
) as {
  descriptors: EditorDescriptors;
  fields: { description: string; instructions: string };
  created: HarnessItem;
  created_draft: HarnessDraft;
  existing: HarnessItem;
  existing_draft: HarnessDraft;
  updated: HarnessItem;
  updated_draft: HarnessDraft;
};

test('Skills guided creation saves independent fields and reopens the backend-assembled document', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/harness/editor/descriptors', skill.descriptors);
  fixtureAPI.get('/api/harness/items/skill/501', skill.created);
  fixtureAPI.get('/api/harness/items/skill/501/history', [skill.created]);
  fixtureAPI.mock(
    'POST',
    '/api/harness/editor/skill/decode',
    skill.created_draft,
  );
  let saved: HarnessEditorPayload | undefined;
  fixtureAPI.mock(
    'POST',
    '/api/harness/editor/skill',
    ({ request }: APIRequest) => {
      saved = request.postDataJSON();
      return skill.created;
    },
    201,
  );
  await page.goto('/harness/skill/new');
  await page.getByLabel('Name', { exact: true }).fill('guided_skill');
  await page
    .getByLabel('Description / when to use')
    .fill(skill.fields.description);
  await page
    .getByLabel('Instructions', { exact: true })
    .fill(skill.fields.instructions);
  await expect(page.getByLabel('Description / when to use')).toHaveAttribute(
    'placeholder',
    /Use when/,
  );
  await page
    .getByRole('group', { name: 'Supporting files', exact: true })
    .getByRole('button', { name: 'Add row', exact: true })
    .click();
  await page
    .getByLabel('File path', { exact: true })
    .fill('references/checklist.md');
  await page
    .getByLabel('File content', { exact: true })
    .fill('Check errors and boundaries.');
  await page.getByRole('button', { name: 'Create Skill', exact: true }).click();
  await expect(page).toHaveURL(/\/harness\/skill\/501$/);
  await expect(
    page.getByRole('heading', { name: 'guided_skill', exact: true }),
  ).toBeVisible();
  expect(saved).toMatchObject({
    mode: 'guided',
    common: { name: 'guided_skill' },
    fields: {
      description: skill.fields.description,
      instructions: skill.fields.instructions,
      files: [
        {
          path: 'references/checklist.md',
          content: 'Check errors and boundaries.',
        },
      ],
    },
  });
  expect(saved).not.toHaveProperty('content');
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(page.getByLabel('Instructions', { exact: true })).toHaveValue(
    skill.fields.instructions,
  );
  await expect(page.getByLabel('File path', { exact: true })).toHaveValue(
    'references/checklist.md',
  );
});

test('Skills guided editing preserves unknown settings and saves one precise version snapshot', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/harness/editor/descriptors', skill.descriptors);
  fixtureAPI.get('/api/harness/items/skill/601', skill.existing);
  fixtureAPI.get('/api/harness/items/skill/601/history', [skill.existing]);
  fixtureAPI.get('/api/harness/items/skill/602', skill.updated);
  fixtureAPI.get('/api/harness/items/skill/602/history', [
    skill.updated,
    skill.existing,
  ]);
  fixtureAPI.mock(
    'POST',
    '/api/harness/editor/skill/decode',
    ({ request }: APIRequest) =>
      request.postDataJSON().content.body === skill.updated.content!.body
        ? skill.updated_draft
        : skill.existing_draft,
  );
  let saved: HarnessEditorPayload | undefined;
  fixtureAPI.mock(
    'PUT',
    '/api/harness/editor/skill/601',
    ({ request }: APIRequest) => {
      saved = request.postDataJSON();
      return skill.updated;
    },
  );
  await page.goto('/harness/skill/601');
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await page
    .getByLabel('Instructions', { exact: true })
    .fill('Preserve the full review instructions and the final sentinel.');
  await page.getByRole('button', { name: 'Save Skill', exact: true }).click();
  await expect(page).toHaveURL(/\/harness\/skill\/602$/);
  expect(saved).toMatchObject({
    expected_version: 1,
    expected_updated_at: '2026-11-05T12:00:00.123456Z',
    dirty_paths: ['/fields/instructions'],
    extensions: skill.existing_draft.extensions,
  });
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(page.getByLabel('Instructions', { exact: true })).toHaveValue(
    'Preserve the full review instructions and the final sentinel.',
  );
  await expect(page.getByRole('tab', { name: 'Guided' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
});

for (const kind of harnessKinds) {
  test(`${kind} creation assembles every independent field and reopens it`, async ({
    page,
    fixtureAPI,
  }) => {
    const example = harnessEditorFixture.cases[kind];
    const definition = harnessEditorFixture.descriptors.types[kind];
    fixtureAPI.get(
      '/api/harness/editor/descriptors',
      harnessEditorFixture.descriptors,
    );
    fixtureAPI.get(
      `/api/harness/items/${kind}/${example.item.id}`,
      example.item,
    );
    fixtureAPI.get(`/api/harness/items/${kind}/${example.item.id}/history`, [
      example.item,
    ]);
    fixtureAPI.mock(
      'POST',
      `/api/harness/editor/${kind}/decode`,
      example.draft,
    );
    let saved: HarnessEditorPayload | undefined;
    fixtureAPI.mock(
      'POST',
      `/api/harness/editor/${kind}`,
      ({ request }: APIRequest) => {
        saved = request.postDataJSON();
        return example.item;
      },
      201,
    );
    await page.goto(`/harness/${kind}/new`);
    await fillHarnessExample(page, kind);
    await expectDocumentContained(page);
    await expectMainContained(page);
    await expectControlsUnclipped(page);
    expect(
      await page.locator('form').evaluate((form) =>
        Array.from(
          form.querySelectorAll<
            HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
          >('input, select, textarea'),
        )
          .filter((input) => input.willValidate && !input.checkValidity())
          .map((input) => ({
            label: input.labels?.[0]?.textContent,
            value: input.value,
            message: input.validationMessage,
          })),
      ),
    ).toEqual([]);
    await page
      .getByRole('button', { name: `Create ${definition.label}`, exact: true })
      .click();
    await expect(page).toHaveURL(
      new RegExp(`/harness/${kind}/${example.item.id}$`),
    );
    expect(saved).toMatchObject({
      mode: 'guided',
      common: Object.fromEntries(
        [
          ...harnessEditorFixture.descriptors.common,
          ...(definition.common_fields ?? []),
        ].map((field) => [field.key, example.common[field.key]]),
      ),
      fields: example.fields,
      extensions: example.extensions,
    });
    expect(saved).not.toHaveProperty('content');
    expect(
      fixtureAPI.requests.filter(
        (entry) =>
          entry.method === 'POST' &&
          new URL(entry.url).pathname === `/api/harness/editor/${kind}`,
      ),
    ).toHaveLength(1);
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    const changed = definition.fields.find(
      (field) => field.key === example.changed_field,
    )!;
    await expect(page.getByLabel(changed.label, { exact: true })).toHaveValue(
      String(example.fields[example.changed_field]),
    );
    await expect(page.getByRole('tab', { name: 'Guided' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expectDocumentContained(page);
    await expectMainContained(page);
  });

  test(`${kind} editing and Raw roundtrip retain unknown settings and precise CAS`, async ({
    page,
    fixtureAPI,
  }) => {
    const example = harnessEditorFixture.cases[kind];
    const definition = harnessEditorFixture.descriptors.types[kind];
    fixtureAPI.get(
      '/api/harness/editor/descriptors',
      harnessEditorFixture.descriptors,
    );
    fixtureAPI.get(
      `/api/harness/items/${kind}/${example.item.id}`,
      example.item,
    );
    fixtureAPI.get(`/api/harness/items/${kind}/${example.item.id}/history`, [
      example.item,
    ]);
    fixtureAPI.get(
      `/api/harness/items/${kind}/${example.updated.id}`,
      example.updated,
    );
    fixtureAPI.get(`/api/harness/items/${kind}/${example.updated.id}/history`, [
      example.updated,
      example.item,
    ]);
    fixtureAPI.mock(
      'POST',
      `/api/harness/editor/${kind}/decode`,
      ({ request }: APIRequest) =>
        JSON.stringify(request.postDataJSON().content) ===
        JSON.stringify(example.updated.content)
          ? example.updated_draft
          : example.draft,
    );
    fixtureAPI.mock('POST', `/api/harness/editor/${kind}/preview`, {
      content: example.item.content,
      draft: example.draft,
    });
    let saved: HarnessEditorPayload | undefined;
    fixtureAPI.mock(
      'PUT',
      `/api/harness/editor/${kind}/${example.item.id}`,
      ({ request }: APIRequest) => {
        saved = request.postDataJSON();
        return example.updated;
      },
    );
    await page.goto(`/harness/${kind}/${example.item.id}`);
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    const changed = definition.fields.find(
      (field) => field.key === example.changed_field,
    )!;
    await expect(page.getByLabel(changed.label, { exact: true })).toHaveValue(
      String(example.fields[example.changed_field]),
    );
    await page.getByRole('tab', { name: 'Raw', exact: true }).click();
    await expect(
      page.getByLabel('Raw definition', { exact: true }),
    ).toHaveValue(example.draft.raw);
    await page.getByRole('tab', { name: 'Guided', exact: true }).click();
    await expect(page.getByLabel(changed.label, { exact: true })).toHaveValue(
      String(example.fields[example.changed_field]),
    );
    await page
      .getByLabel(changed.label, { exact: true })
      .fill(String(example.updated_value));
    await page
      .getByRole('button', { name: `Save ${definition.label}`, exact: true })
      .click();
    await expect(page).toHaveURL(
      new RegExp(`/harness/${kind}/${example.updated.id}$`),
    );
    expect(saved).toMatchObject({
      expected_version: example.item.version,
      expected_updated_at: example.item.updated_at,
      original_content: example.item.content,
      source_name: example.item.name,
      dirty_paths: [`/fields/${example.changed_field}`],
      extensions: example.draft.extensions,
      common: {
        agents: example.item.agents,
        enabled: example.item.enabled,
        sort_key: example.item.sort_key,
      },
    });
    expect(
      fixtureAPI.requests.filter((entry) => entry.method === 'PUT'),
    ).toHaveLength(1);
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(page.getByLabel(changed.label, { exact: true })).toHaveValue(
      String(example.updated_value),
    );
    await expectDocumentContained(page);
    await expectMainContained(page);
    await expectControlsUnclipped(page);
  });
}
