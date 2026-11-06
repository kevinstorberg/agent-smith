import { test, expect, type APIRequest } from './fixtures';
import { actionItem } from '../src/pages/__tests__/actionItemFixture';
import { expectSortableHeaderLayout } from './sortableHeaderLayout';
import {
  expectControlContained,
  expectDocumentContained,
  expectMainContained,
} from './geometry';
import { enlargeComputedText } from './typography';

const initialProject = {
  id: 7,
  name: 'WGU',
  description: 'Coursework and assessments',
  revision: 2,
  created_at: '2026-11-01T12:00:00Z',
  updated_at: '2026-11-05T14:00:00Z',
};

test('project management follows the existing workspace, form and action-item navigation', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  let project = { ...initialProject };
  fixtureAPI.get('/api/action-items/projects', () => ({
    items: [project],
    total: 1,
  }));
  fixtureAPI.get('/api/action-items', () => ({
    items: [actionItem(1, { project: project.name })],
    total: 1,
  }));
  fixtureAPI.get('/api/projects', () => ({ items: [project], total: 1 }));
  fixtureAPI.get('/api/projects/7', () => project);
  fixtureAPI.mock('PATCH', '/api/projects/7', ({ request }: APIRequest) => {
    expect(request.postDataJSON()).toEqual({
      expected_revision: 2,
      name: 'School / WGU',
      description: 'Coursework\n\nFinish assessments.',
    });
    project = { ...project, ...request.postDataJSON(), revision: 3 };
    return project;
  });
  await page.goto('/action-items');
  const toolbar = page.getByRole('group', { name: 'Project management' });
  const manage = toolbar.getByRole('link', { name: 'Manage projects' });
  const create = toolbar.getByRole('button', {
    name: 'New project',
    exact: true,
  });
  await expect(manage).toHaveClass(/btn btn-sm/);
  await expect(manage).toHaveCSS('text-decoration-line', 'none');
  await manage.scrollIntoViewIfNeeded();
  const controls = await Promise.all([
    manage.boundingBox(),
    create.boundingBox(),
  ]);
  expect(Math.abs(controls[0]!.y - controls[1]!.y)).toBeLessThanOrEqual(1);
  await manage.click();
  await expect(
    page.getByRole('heading', { name: 'Projects', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('link', { name: '+ New project', exact: true }),
  ).toHaveCSS('text-decoration-line', 'none');
  await page.getByRole('row').filter({ hasText: 'WGU' }).click();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  const name = page.getByRole('textbox', { name: 'Name', exact: true });
  const description = page.getByRole('textbox', {
    name: 'Description',
    exact: true,
  });
  await expect(name).toHaveClass(/input detail-title-input/);
  await expect(description).toHaveClass('input');
  await expectControlContained(name, page.locator('#main-content'));
  await expectControlContained(description, page.locator('#main-content'));
  await name.fill('School / WGU');
  await description.fill('Coursework\n\nFinish assessments.');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'School / WGU', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Finish assessments.', { exact: true }),
  ).toBeVisible();
  await page.getByRole('link', { name: 'View action items' }).click();
  await expect(
    page.getByRole('tab', { name: 'School / WGU', exact: true }),
  ).toHaveAttribute('aria-selected', 'true');
  await expect(
    page.getByRole('columnheader', { name: 'Title' }).getByRole('button'),
  ).toBeVisible();
  await expectDocumentContained(page);
  await expectMainContained(page);
  await page.screenshot({
    path: testInfo.outputPath('project-assignment-after-rename.png'),
  });
});

test('new project fields validate, create and keep standard controls reachable with doubled text', async ({
  page,
  fixtureAPI,
}, testInfo) => {
  fixtureAPI.mock(
    'POST',
    '/api/projects',
    ({ request }: APIRequest) => {
      expect(request.postDataJSON()).toEqual({
        name: 'WGU',
        description: 'Study plans.',
      });
      return initialProject;
    },
    201,
  );
  fixtureAPI.get('/api/projects/7', initialProject);
  await page.goto('/projects/new');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByLabel('Name', { exact: true })).toHaveAttribute(
    'aria-invalid',
    'true',
  );
  await page.getByLabel('Name', { exact: true }).fill('  WGU  ');
  await page.getByLabel('Description', { exact: true }).fill('Study plans.');
  await enlargeComputedText(page);
  for (const label of ['Name', 'Description'])
    await expectControlContained(
      page.getByLabel(label, { exact: true }),
      page.locator('#main-content'),
    );
  const save = page.getByRole('button', { name: 'Save', exact: true });
  const cancel = page.getByRole('button', { name: 'Cancel', exact: true });
  await expectControlContained(save, page.locator('#main-content'));
  await expectControlContained(cancel, page.locator('#main-content'));
  await expectDocumentContained(page);
  await page.screenshot({ path: testInfo.outputPath('project-form-2x.png') });
  await save.click();
  await expect(
    page.getByRole('heading', { name: 'WGU', exact: true }),
  ).toBeVisible();
});

for (const font of ['default', 'Arial']) {
  test(`Projects headers retain whole labels and arrows with ${font} text at normal and doubled sizes`, async ({
    page,
    fixtureAPI,
  }, testInfo) => {
    const project = {
      ...initialProject,
      name: 'Very long project name '.repeat(8).trim(),
      description: 'Long descriptive context '.repeat(40),
    };
    fixtureAPI.get('/api/projects', { items: [project], total: 1 });
    await page.goto('/projects');
    await expect(page.getByText(project.name, { exact: true })).toBeVisible();
    if (font === 'Arial')
      await page.addStyleTag({
        content: '* { font-family: Arial, sans-serif !important; }',
      });
    await expectSortableHeaderLayout(page, testInfo, {
      table: page.getByRole('table', { name: 'Projects', exact: true }),
      scrollRegion: page.getByRole('region', {
        name: 'Projects list',
        exact: true,
      }),
      labels: ['Name', 'Description', 'Updated'],
      artifactPrefix: `projects-${font.toLowerCase()}`,
    });
    await expectDocumentContained(page);
    await expectMainContained(page);
  });
}

test('Projects header toggles preserve search and pagination preferences without refresh prose', async ({
  page,
  fixtureAPI,
}) => {
  fixtureAPI.get('/api/projects', { items: [initialProject], total: 30 });
  await page.goto('/projects?q=course&offset=10&sort=updated_desc&keep=1');
  await expect(page.getByText('WGU', { exact: true })).toBeVisible();
  for (const [label, sorts] of [
    ['Name', ['name_asc', 'name_desc']],
    ['Description', ['description_asc', 'description_desc']],
    ['Updated', ['updated_desc', 'updated_asc']],
  ] as const) {
    for (const sort of sorts) {
      const header = page.getByRole('columnheader', {
        name: label,
        exact: true,
      });
      await header.getByRole('button').click();
      await expect(header).toHaveAttribute(
        'aria-sort',
        sort.endsWith('_desc') ? 'descending' : 'ascending',
      );
      const query = new URL(page.url()).searchParams;
      expect(Object.fromEntries(query)).toMatchObject({
        q: 'course',
        sort,
        offset: '0',
        keep: '1',
      });
      await expect(
        page.getByText(
          /Showing previous results|Reordering is unavailable|Updating results/,
        ),
      ).toHaveCount(0);
    }
  }
  await page.reload();
  await expect(
    page.getByRole('columnheader', { name: 'Updated', exact: true }),
  ).toHaveAttribute('aria-sort', 'ascending');
});
