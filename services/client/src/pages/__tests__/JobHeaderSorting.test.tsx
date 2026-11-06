import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { Job, Paginated } from '../../api';
import { api } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { jobFixture } from '../../../browser-tests/operationsFixture';
import { JobsIndexPage } from '../JobsIndexPage';

vi.mock('../../api', () => ({
  api: { jobs: { list: vi.fn(), setScheduling: vi.fn() } },
}));
const response = (name: string): Paginated<Job> => ({
  items: [{ ...jobFixture(), name }],
  total: 30,
});
const header = (name: string) =>
  screen.getByRole('columnheader', { name: new RegExp(`^${name}$`) });
const button = (name: string) => within(header(name)).getByRole('button');

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.resetAllMocks();
  vi.mocked(api.jobs.list).mockResolvedValue(response('Accepted job'));
});

it.each([
  ['Name', 'name', 'name_desc'],
  ['Last Updated', 'updated', 'updated_asc'],
])(
  'toggles %s at page zero without changing scheduling criteria or utility controls',
  async (label, first, second) => {
    renderWithProviders(<JobsIndexPage />, {
      initialEntries: [
        '/jobs?q=release&schedule_enabled=false&sort=name_desc&offset=20&keep=1',
      ],
    });
    await screen.findByText('Accepted job');
    expect(
      screen.queryByRole('combobox', { name: 'Sort jobs' }),
    ).not.toBeInTheDocument();
    expect(
      within(header('Schedule')).queryByRole('button'),
    ).not.toBeInTheDocument();
    expect(
      within(header('Actions')).queryByRole('button'),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Scheduling' })).toHaveValue(
      'false',
    );
    for (const sort of [first, second]) {
      fireEvent.click(button(label));
      await waitFor(() =>
        expect(api.jobs.list).toHaveBeenLastCalledWith({
          q: 'release',
          schedule_enabled: false,
          sort,
          limit: 10,
          offset: 0,
        }),
      );
      await waitFor(() =>
        expect(header(label)).toHaveAttribute(
          'aria-sort',
          sort === 'updated' || sort === 'name_desc'
            ? 'descending'
            : 'ascending',
        ),
      );
    }
    expect(api.jobs.setScheduling).not.toHaveBeenCalled();
  },
);

it('keeps accepted jobs quiet and focused while disabling stale scheduling writes and rejecting late sort results', async () => {
  let resolveAsc!: (value: Paginated<Job>) => void;
  let resolveDesc!: (value: Paginated<Job>) => void;
  const asc = new Promise<Paginated<Job>>((resolve) => {
    resolveAsc = resolve;
  });
  const desc = new Promise<Paginated<Job>>((resolve) => {
    resolveDesc = resolve;
  });
  vi.mocked(api.jobs.list).mockImplementation((options) =>
    options?.sort === 'name'
      ? asc
      : options?.sort === 'name_desc'
        ? desc
        : Promise.resolve(response('Accepted job')),
  );
  renderWithProviders(<JobsIndexPage />, { initialEntries: ['/jobs'] });
  await screen.findByText('Accepted job');
  const name = button('Name');
  name.focus();
  fireEvent.click(name);
  await waitFor(() =>
    expect(api.jobs.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort: 'name', offset: 0 }),
    ),
  );
  expect(screen.getByText('Accepted job')).toBeVisible();
  expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
  expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
  expect(header('Name')).not.toHaveAttribute('aria-sort');
  expect(
    screen.getByRole('button', {
      name: 'Pause automatic runs for Accepted job',
    }),
  ).toBeDisabled();
  expect(name).toHaveFocus();
  fireEvent.click(name);
  await waitFor(() =>
    expect(api.jobs.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort: 'name_desc' }),
    ),
  );
  await act(async () => resolveDesc(response('Accepted descending')));
  await screen.findByText('Accepted descending');
  await act(async () => resolveAsc(response('Late ascending')));
  expect(screen.queryByText('Late ascending')).not.toBeInTheDocument();
  expect(header('Name')).toHaveAttribute('aria-sort', 'descending');
  expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'false');
  expect(name).toHaveFocus();
});

it.each(['header', 'retry'] as const)(
  'retains headers and reports error-to-%s retry busy before accepting empty jobs',
  async (origin) => {
    let finish!: (value: Paginated<Job>) => void;
    const retry = new Promise<Paginated<Job>>((resolve) => {
      finish = resolve;
    });
    vi.mocked(api.jobs.list)
      .mockRejectedValueOnce(new Error('Unavailable'))
      .mockReturnValueOnce(retry);
    renderWithProviders(<JobsIndexPage />, { initialEntries: ['/jobs'] });
    await screen.findByRole('alert');
    expect(screen.getAllByRole('columnheader')).toHaveLength(4);
    const table = screen.getByRole('table');
    expect(table).toHaveAttribute('aria-busy', 'false');
    const name = button('Name');
    const trigger =
      origin === 'header'
        ? name
        : screen.getByRole('button', { name: 'Retry' });
    trigger.focus();
    fireEvent.click(trigger);
    await waitFor(() =>
      expect(api.jobs.list).toHaveBeenLastCalledWith(
        expect.objectContaining({
          sort: origin === 'header' ? 'name' : 'updated',
        }),
      ),
    );
    expect(table).toHaveAttribute('aria-busy', 'true');
    expect(header('Name')).not.toHaveAttribute('aria-sort');
    await act(async () => finish({ items: [], total: 0 }));
    expect(await screen.findByText('No jobs found')).toBeVisible();
    expect(table).toHaveAttribute('aria-busy', 'false');
    if (origin === 'header') expect(name).toHaveFocus();
  },
);

it('preserves pause updates and current accepted rows when their refresh fails', async () => {
  vi.mocked(api.jobs.list)
    .mockResolvedValueOnce(response('Accepted job'))
    .mockRejectedValueOnce(new Error('Unavailable'));
  vi.mocked(api.jobs.setScheduling).mockResolvedValue({
    ...jobFixture(),
    name: 'Accepted job',
    schedule_enabled: false,
    version: 2,
  });
  renderWithProviders(<JobsIndexPage />, { initialEntries: ['/jobs'] });
  await screen.findByText('Accepted job');
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Pause automatic runs for Accepted job',
    }),
  );
  await screen.findByRole('alert');
  expect(api.jobs.setScheduling).toHaveBeenCalledWith(1, {
    schedule_enabled: false,
  });
  expect(screen.getByText('Accepted job')).toBeVisible();
  expect(
    screen.getByRole('button', {
      name: 'Resume automatic runs for Accepted job',
    }),
  ).toBeEnabled();
  expect(header('Last Updated')).not.toHaveAttribute('aria-sort');
});
