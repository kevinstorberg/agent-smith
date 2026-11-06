import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { Route, Routes, useLocation } from 'react-router';
import { renderWithProviders } from '../../test-utils';
import { ProjectsIndexPage } from '../ProjectsIndexPage';
import { ProjectDetailPage } from '../ProjectDetailPage';
import { POLL_INTERVAL_MS } from '../../constants';
import { deferred } from './actionItemFixture';

vi.mock('../../api', async (original) => ({
  ...(await original<typeof import('../../api')>()),
  api: {
    projects: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn() },
  },
}));
import { api, ApiError } from '../../api';

const project = {
  id: 7,
  name: 'WGU',
  description: 'Coursework and assessments',
  revision: 2,
  created_at: '2026-11-01T12:00:00Z',
  updated_at: '2026-11-05T14:00:00Z',
};
function Location() {
  const location = useLocation();
  return (
    <output aria-label="Current route">
      {location.pathname}
      {location.search}
    </output>
  );
}
function renderPage(url = '/projects/7') {
  return renderWithProviders(
    <>
      <Location />
      <Routes>
        <Route path="/projects" element={<ProjectsIndexPage />} />
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
        <Route path="/action-items" element={<p>Assigned action items</p>} />
      </Routes>
    </>,
    { initialEntries: [url] },
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.mocked(api.projects.get).mockResolvedValue(project);
  vi.mocked(api.projects.list).mockResolvedValue({
    items: [project],
    total: 1,
  });
  vi.mocked(api.projects.create).mockResolvedValue({ ...project, revision: 1 });
  vi.mocked(api.projects.update).mockImplementation(async (_id, fields) => ({
    ...project,
    ...fields,
    revision: 3,
  }));
});
afterEach(() => vi.useRealTimers());

it('uses a searchable, paginated table with header sorting and row navigation', async () => {
  renderPage('/projects?q=course&sort=updated_desc&offset=0&keep=1');
  await screen.findByText('WGU');
  expect(api.projects.list).toHaveBeenLastCalledWith({
    q: 'course',
    sort: 'updated_desc',
    limit: 10,
    offset: 0,
  });
  expect(
    screen.queryByRole('combobox', { name: /sort/i }),
  ).not.toBeInTheDocument();
  for (const [name, sort] of [
    ['Name', 'name_asc'],
    ['Description', 'description_asc'],
    ['Updated', 'updated_desc'],
  ] as const) {
    fireEvent.click(
      within(screen.getByRole('columnheader', { name })).getByRole('button'),
    );
    await waitFor(() =>
      expect(api.projects.list).toHaveBeenLastCalledWith({
        q: 'course',
        sort,
        limit: 10,
        offset: 0,
      }),
    );
    expect(screen.getByLabelText('Current route')).toHaveTextContent('keep=1');
  }
  fireEvent.click(screen.getByText('WGU'));
  await screen.findByRole('heading', { name: 'WGU' });
  expect(
    screen.getByRole('link', { name: 'View action items' }),
  ).toHaveAttribute('href', '/action-items?project=WGU');
});

it('quietly polls the list every fifteen seconds and retries a failed read', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.mocked(api.projects.list).mockRejectedValueOnce(new Error('Unavailable'));
  renderPage('/projects');
  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
  await screen.findByText('WGU');
  const count = vi.mocked(api.projects.list).mock.calls.length;
  await act(async () => {
    vi.advanceTimersByTime(POLL_INTERVAL_MS);
  });
  expect(api.projects.list).toHaveBeenCalledTimes(count + 1);
  expect(
    screen.queryByText(/showing previous|reordering is|updating results/i),
  ).not.toBeInTheDocument();
});

it('creates from independent fields with examples and prevents invalid submissions', async () => {
  renderPage('/projects/new');
  const name = screen.getByRole('textbox', { name: 'Name' });
  const description = screen.getByRole('textbox', { name: 'Description' });
  expect(name).toHaveAttribute('placeholder', 'e.g. WGU');
  expect(description).toHaveAttribute(
    'placeholder',
    'e.g. Coursework, assessments, and study plans.',
  );
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(name).toHaveAttribute('aria-invalid', 'true');
  expect(api.projects.create).not.toHaveBeenCalled();
  fireEvent.change(name, { target: { value: '  WGU  ' } });
  fireEvent.change(description, { target: { value: 'Goals\n\nNext steps' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() =>
    expect(api.projects.create).toHaveBeenCalledWith({
      name: 'WGU',
      description: 'Goals\n\nNext steps',
    }),
  );
  await screen.findByRole('heading', { name: 'WGU' });
});

it('sends only changed metadata with the original revision and cancels drafts without writing', async () => {
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), {
    target: { value: 'Draft' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.getByRole('heading', { name: 'WGU' })).toBeInTheDocument();
  expect(api.projects.update).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Description' }), {
    target: { value: '' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() =>
    expect(api.projects.update).toHaveBeenCalledWith(7, {
      expected_revision: 2,
      description: '',
    }),
  );
});

it('retains drafts on conflicts and requires an explicit reload before another save', async () => {
  vi.mocked(api.projects.update).mockRejectedValueOnce(
    new ApiError('Project changed', 409),
  );
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
  vi.mocked(api.projects.get).mockResolvedValue({
    ...project,
    name: 'Saved elsewhere',
    revision: 3,
  });
  fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), {
    target: { value: 'My draft' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('My draft');
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  await waitFor(() => expect(api.projects.get).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole('button', { name: 'Reload saved version' }));
  expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue(
    'Saved elsewhere',
  );
  fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), {
    target: { value: 'Reviewed draft' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() =>
    expect(api.projects.update).toHaveBeenLastCalledWith(7, {
      expected_revision: 3,
      name: 'Reviewed draft',
    }),
  );
});

it('does not poll over an active draft and allows editing descriptions for exact legacy names', async () => {
  vi.mocked(api.projects.get).mockResolvedValue({
    ...project,
    name: '  Legacy\nname  ',
  });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
  vi.useFakeTimers();
  await act(async () => {
    vi.advanceTimersByTime(POLL_INTERVAL_MS * 2);
  });
  expect(api.projects.get).toHaveBeenCalledTimes(1);
  vi.useRealTimers();
  fireEvent.change(screen.getByRole('textbox', { name: 'Description' }), {
    target: { value: 'Legacy description' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() =>
    expect(api.projects.update).toHaveBeenCalledWith(7, {
      expected_revision: 2,
      description: 'Legacy description',
    }),
  );
});

it('lets a duplicate name be corrected without discarding the description draft', async () => {
  vi.mocked(api.projects.update).mockRejectedValueOnce(
    new ApiError(
      'A project with this name already exists. Choose a different name.',
      409,
    ),
  );
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), {
    target: { value: 'Duplicate' },
  });
  fireEvent.change(screen.getByRole('textbox', { name: 'Description' }), {
    target: { value: 'Retained description' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'A project with this name already exists.',
  );
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled(),
  );
  expect(screen.getByRole('textbox', { name: 'Description' })).toHaveValue(
    'Retained description',
  );
  fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), {
    target: { value: 'Unique' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() =>
    expect(api.projects.update).toHaveBeenLastCalledWith(7, {
      expected_revision: 2,
      name: 'Unique',
      description: 'Retained description',
    }),
  );
});

it('keeps an oversized description out of storage and reports its field error', async () => {
  renderPage('/projects/new');
  fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), {
    target: { value: 'Valid' },
  });
  fireEvent.change(screen.getByRole('textbox', { name: 'Description' }), {
    target: { value: 'x'.repeat(100_001) },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(screen.getByRole('textbox', { name: 'Description' })).toHaveAttribute(
    'aria-invalid',
    'true',
  );
  expect(
    screen.getByRole('textbox', { name: 'Description' }),
  ).toHaveAccessibleDescription(
    /Description must contain 100000 characters or fewer\./,
  );
  expect(api.projects.create).not.toHaveBeenCalled();
});

it('does not navigate back into an editor after its delayed save completes on another page', async () => {
  const pending = deferred<typeof project>();
  vi.mocked(api.projects.create).mockReturnValue(pending.promise);
  renderPage('/projects/new');
  fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), {
    target: { value: 'WGU' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled();
  fireEvent.click(screen.getByRole('link', { name: /Back to projects/ }));
  await screen.findByRole('heading', { name: 'Projects' });
  await act(async () => {
    pending.resolve(project);
  });
  expect(screen.getByRole('heading', { name: 'Projects' })).toBeInTheDocument();
  expect(screen.getByLabelText('Current route')).toHaveTextContent('/projects');
  expect(
    screen.queryByRole('button', { name: 'Edit' }),
  ).not.toBeInTheDocument();
});
