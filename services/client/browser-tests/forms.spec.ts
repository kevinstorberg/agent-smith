import { test, expect } from './fixtures';
import {
  harnessEditorFixture,
  fillHarnessExample,
  harnessKinds,
} from './harnessEditorFixture';
import { expectContrast } from './contrast';
import {
  expectControlContained,
  expectControlsUnclipped,
  expectDocumentContained,
  expectMainContained,
} from './geometry';

const agents = {
  agents: ['claude', 'codex', 'gemini'],
  virtual_agents: ['review_graph_with_an_explicit_purpose'],
};
for (const kind of harnessKinds) {
  test(`${kind} creation keeps labels and field groups usable on narrow screens`, async ({
    page,
    fixtureAPI,
  }) => {
    fixtureAPI.get(
      '/api/harness/editor/descriptors',
      harnessEditorFixture.descriptors,
    );
    fixtureAPI.mock(
      'POST',
      `/api/harness/editor/${kind}`,
      {
        detail: [
          {
            loc: ['body', 'common', 'name'],
            msg: 'Name must use lowercase letters, digits, and underscores.',
            type: 'value_error',
          },
        ],
      },
      422,
    );
    await page.goto(`/harness/${kind}/new`);
    for (const label of [
      'Name',
      'Project',
      'Sort order',
      'Initial device',
      'Initial repository',
    ]) {
      const control = page.getByLabel(label, { exact: true });
      await expect(control).toBeVisible();
      await expectControlContained(control, page.locator('#main-content'));
    }
    await fillHarnessExample(page, kind);
    const name = page.getByRole('textbox', { name: 'Name', exact: true });
    await name.fill('invalid name');
    await page
      .getByRole('button', {
        name: `Create ${harnessEditorFixture.descriptors.types[kind].label}`,
        exact: true,
      })
      .click();
    await expect(name).toHaveAttribute('aria-invalid', 'true');
    await expect(name).toHaveAccessibleDescription(
      /letters|spaces|alphanumeric|name/i,
    );
    await expectContrast(page.locator('.harness-editor .text-danger').first());
    await expect(
      page.getByRole('link', { name: /^← Back to/ }),
    ).toHaveAttribute(
      'href',
      `/harness/${kind === 'agent' ? 'agents' : `${kind}s`}`,
    );
    for (const checkbox of await page.locator('input[type="checkbox"]').all()) {
      const bounds = await checkbox.boundingBox();
      expect(bounds).not.toBeNull();
      expect(Math.abs(bounds!.width - bounds!.height)).toBeLessThanOrEqual(1);
    }
    await expectDocumentContained(page);
    await expectMainContained(page);
    await expectControlsUnclipped(page);
  });
}

test('Rule editing and deployment errors keep visible labels and reachable controls', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/harness/agents/assignable', agents);
  const example = harnessEditorFixture.cases.rule;
  fixtureAPI.get(
    '/api/harness/editor/descriptors',
    harnessEditorFixture.descriptors,
  );
  fixtureAPI.mock('POST', '/api/harness/editor/rule/decode', example.draft);
  fixtureAPI.get('/api/harness/items/rule/1', { ...example.item, id: 1 });
  fixtureAPI.get('/api/harness/items/rule/1/history', []);
  await page.goto('/harness/rule/1');
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  for (const label of ['Name', 'Project', 'Sort order', 'Instructions'])
    await expect(page.getByLabel(label, { exact: true })).toBeVisible();
  await expect(
    page.getByRole('group', { name: 'Available to agents', exact: true }),
  ).toBeVisible();
  await expectDocumentContained(page);
  await expectMainContained(page);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: '+ Add', exact: true }).click();
  const form = page.getByRole('group', {
    name: 'New Configuration',
    exact: true,
  });
  const repo = form.getByRole('textbox', { name: 'Repository', exact: true });
  await repo.fill('relative/path');
  await expect(repo).toHaveAccessibleDescription(
    'Must be * or an absolute path',
  );
  await expect(
    form.getByRole('button', { name: 'Add', exact: true }),
  ).toBeDisabled();
  await expectContrast(form.locator('.field-error'));
  await expectControlContained(repo, form);
  await form.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(form).not.toBeVisible();
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
});
