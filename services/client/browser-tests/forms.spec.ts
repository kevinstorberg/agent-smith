import { test, expect } from './fixtures';
import { harnessFixture } from './harnessFixture';
import { expectContrast } from './contrast';
import { expectControlContained, expectControlsUnclipped, expectDocumentContained, expectMainContained } from './geometry';

const agents = { agents: ['claude', 'codex', 'gemini'], virtual_agents: ['review_graph_with_an_explicit_purpose'] };
for (const kind of ['rule', 'skill', 'tool', 'hook', 'agent']) {
  test(`${kind} creation keeps labels and field groups usable on narrow screens`, async ({ page, fixtureAPI }) => {
    fixtureAPI.get('/api/harness/agents/assignable', agents);
    await page.goto(`/harness/${kind}/new`);
    for (const label of ['Name', 'Project', 'Sort Order', 'Device', 'Repository']) {
      const control = page.getByLabel(label, { exact: true });
      await expect(control).toBeVisible();
      await expectControlContained(control, page.locator('#main-content'));
    }
    const name = page.getByRole('textbox', { name: 'Name', exact: true });
    await name.fill('invalid name');
    await expect(name).toHaveAttribute('aria-invalid', 'true');
    await expect(name).toHaveAccessibleDescription(/letters|spaces|alphanumeric|name/i);
    await expectContrast(page.locator('.field-feedback').getByText(/./).first());
    await expect(page.getByRole('link', { name: /^← Back to/ })).toHaveAttribute('href', `/harness/${kind === 'agent' ? 'agents' : `${kind}s`}`);
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

test('Rule editing and deployment errors keep visible labels and reachable controls', async ({ page, fixtureAPI }) => {
  fixtureAPI.get('/api/harness/agents/assignable', agents);
  fixtureAPI.get('/api/harness/items/rule/1', harnessFixture());
  fixtureAPI.get('/api/harness/items/rule/1/history', []);
  await page.goto('/harness/rule/1');
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  for (const label of ['Name', 'Project', 'Sort Order', 'Body']) await expect(page.getByLabel(label, { exact: true })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Agents', exact: true })).toBeVisible();
  await expectDocumentContained(page);
  await expectMainContained(page);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: '+ Add', exact: true }).click();
  const form = page.getByRole('group', { name: 'New Configuration', exact: true });
  const repo = form.getByRole('textbox', { name: 'Repository', exact: true });
  await repo.fill('relative/path');
  await expect(repo).toHaveAccessibleDescription('Must be * or an absolute path');
  await expect(form.getByRole('button', { name: 'Add', exact: true })).toBeDisabled();
  await expectContrast(form.locator('.field-error'));
  await expectControlContained(repo, form);
  await form.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(form).not.toBeVisible();
  await expectDocumentContained(page);
  await expectMainContained(page);
  await expectControlsUnclipped(page);
});
