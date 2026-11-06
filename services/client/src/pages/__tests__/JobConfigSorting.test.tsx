import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Link, Route, Routes } from 'react-router';
import { api } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { JobDetailPage } from '../JobDetailPage';
import { jobFixture } from './jobFixture';
import { jobConfigSortingRows } from './jobConfigSortingFixture';
import { POLL_INTERVAL_MS } from '../../constants';

vi.mock('../../api', () => ({
  api: {
    jobs: {
      get: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
      setScheduling: vi.fn(),
      runNow: vi.fn(),
      executions: vi.fn(),
      execution: vi.fn(),
    },
  },
}));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.jobs.get).mockImplementation(async (id) => ({
    ...jobFixture,
    id,
    name: `Job ${id}`,
    configs: jobConfigSortingRows.map((row) => ({
      ...row,
      id: row.id + (id - jobFixture.id) * 100,
      job_id: id,
    })),
  }));
  vi.mocked(api.jobs.executions).mockResolvedValue({ items: [], total: 0 });
});
afterEach(() => vi.useRealTimers());

function open() {
  return renderWithProviders(
    <>
      <Link to="/jobs/43">Other job</Link>
      <Routes>
        <Route path="/jobs/:id" element={<JobDetailPage />} />
      </Routes>
    </>,
    { initialEntries: ['/jobs/42'] },
  );
}
const devices = () =>
  within(screen.getByRole('table', { name: 'Job configurations' }))
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[0].textContent);

it('sorts every config column in both directions without writing or changing canonical configs', async () => {
  const user = userEvent.setup();
  open();
  await screen.findByRole('heading', { name: 'Job 42' });
  expect(devices()).toEqual(['Zulu', 'alpha', 'ALPHA']);
  for (const [label, ascending, descending] of [
    ['Device', ['ALPHA', 'alpha', 'Zulu'], ['Zulu', 'ALPHA', 'alpha']],
    ['Repo', ['alpha', 'Zulu', 'ALPHA'], ['ALPHA', 'Zulu', 'alpha']],
    ['Enabled', ['alpha', 'ALPHA', 'Zulu'], ['ALPHA', 'Zulu', 'alpha']],
    ['Exclude', ['ALPHA', 'Zulu', 'alpha'], ['alpha', 'ALPHA', 'Zulu']],
  ] as const) {
    const button = screen.getByRole('button', { name: label });
    await user.click(button);
    expect(devices()).toEqual(ascending);
    await user.click(button);
    expect(devices()).toEqual(descending);
  }
  expect(jobConfigSortingRows.map((row) => row.id)).toEqual([30, 20, 10]);
  const canonical: Awaited<ReturnType<typeof api.jobs.get>> = await vi.mocked(
    api.jobs.get,
  ).mock.results[0].value;
  expect(canonical.configs?.map((row) => row.id)).toEqual([30, 20, 10]);
  for (const write of [
    api.jobs.update,
    api.jobs.create,
    api.jobs.runNow,
    api.jobs.setScheduling,
    api.jobs.remove,
  ])
    expect(write).not.toHaveBeenCalled();
});

it('resets local sort on real job identity navigation and keeps execution headers unchanged', async () => {
  const user = userEvent.setup();
  open();
  await screen.findByRole('heading', { name: 'Job 42' });
  await user.click(screen.getByRole('button', { name: 'Device' }));
  expect(devices()).toEqual(['ALPHA', 'alpha', 'Zulu']);
  await user.click(screen.getByRole('link', { name: 'Other job' }));
  await screen.findByRole('heading', { name: 'Job 43' });
  expect(devices()).toEqual(['Zulu', 'alpha', 'ALPHA']);
  expect(
    screen.getByRole('columnheader', { name: 'Device' }),
  ).not.toHaveAttribute('aria-sort');
  await user.click(screen.getByRole('button', { name: 'Executions' }));
  expect(screen.getByRole('columnheader', { name: 'Started' })).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Started' })).toBeNull();
  expect(api.jobs.update).not.toHaveBeenCalled();
  expect(api.jobs.runNow).not.toHaveBeenCalled();
});

it('retains the chosen display order when the same job polls fresh configs without altering editor data', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
  const user = userEvent.setup();
  let rows = jobConfigSortingRows;
  vi.mocked(api.jobs.get).mockImplementation(async (id) => ({
    ...jobFixture,
    id,
    name: `Job ${id}`,
    configs: rows.map((row) => ({ ...row })),
  }));
  open();
  await screen.findByRole('heading', { name: 'Job 42' });
  await user.click(screen.getByRole('button', { name: 'Device' }));
  rows = [...jobConfigSortingRows].reverse();
  await act(async () => {
    vi.advanceTimersByTime(POLL_INTERVAL_MS);
  });
  await waitFor(() => expect(api.jobs.get).toHaveBeenCalledTimes(2));
  expect(devices()).toEqual(['ALPHA', 'alpha', 'Zulu']);
  expect(screen.getByRole('columnheader', { name: 'Device' })).toHaveAttribute(
    'aria-sort',
    'ascending',
  );
  await user.click(screen.getByRole('button', { name: 'Edit' }));
  expect(screen.getByLabelText('Description')).toHaveValue(
    jobFixture.description,
  );
  expect(rows.map((row) => row.id)).toEqual([10, 20, 30]);
  expect(api.jobs.update).not.toHaveBeenCalled();
  expect(api.jobs.runNow).not.toHaveBeenCalled();
});
