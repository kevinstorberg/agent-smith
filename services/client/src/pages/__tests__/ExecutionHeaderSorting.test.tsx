import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { Link, Route, Routes } from 'react-router';
import { api } from '../../api';
import type { JobExecution, Paginated } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { JobDetailPage } from '../JobDetailPage';
import { jobFixture } from './jobFixture';
vi.mock('../../api', () => ({
  api: {
    jobs: {
      get: vi.fn(),
      executions: vi.fn(),
      execution: vi.fn(),
      update: vi.fn(),
      runNow: vi.fn(),
    },
  },
}));
const result = (status: string): Paginated<JobExecution> => ({
  items: [
    {
      id: 1,
      job_id: 42,
      status,
      started_at: '2026-01-01T12:00:00Z',
      completed_at: null,
      result: { exit_code: 10 },
    },
  ],
  total: 30,
});
const open = () =>
  renderWithProviders(
    <>
      <Link to="/jobs/43?tab=executions">Other job</Link>
      <Routes>
        <Route path="/jobs/:id" element={<JobDetailPage />} />
      </Routes>
    </>,
    { initialEntries: ['/jobs/42?tab=executions'] },
  );
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.jobs.get).mockImplementation(async (id) => ({
    ...jobFixture,
    id,
    name: `Job ${id}`,
  }));
  vi.mocked(api.jobs.executions).mockResolvedValue(result('Accepted run'));
});
it.each([
  ['Status', 'status_asc', 'status_desc'],
  ['Started', undefined, 'started_asc'],
  ['Completed', 'completed_desc', 'completed_asc'],
  ['Exit', 'exit_asc', 'exit_desc'],
])(
  'toggles %s globally and resets paging without running a job',
  async (label, first, second) => {
    open();
    await screen.findByText('Accepted run');
    const region = screen.getByRole('region', { name: 'Job executions' });
    const table = within(region);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(api.jobs.executions).toHaveBeenLastCalledWith(42, {
        limit: 10,
        offset: 10,
      }),
    );
    const values =
      label === 'Started' ? ['started_asc', undefined] : [first, second];
    for (const sort of values) {
      fireEvent.click(table.getByRole('button', { name: label }));
      await waitFor(() =>
        expect(api.jobs.executions).toHaveBeenLastCalledWith(42, {
          limit: 10,
          offset: 0,
          ...(sort ? { sort } : {}),
        }),
      );
    }
    expect(api.jobs.runNow).not.toHaveBeenCalled();
    expect(api.jobs.update).not.toHaveBeenCalled();
  },
);
it('retains accepted runs and keyboard focus during pending sorts and rejects late responses', async () => {
  open();
  await screen.findByText('Accepted run');
  let finish!: (page: Paginated<JobExecution>) => void;
  vi.mocked(api.jobs.executions).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const region = screen.getByRole('region', { name: 'Job executions' });
  const button = within(region).getByRole('button', { name: 'Status' });
  button.focus();
  fireEvent.click(button);
  await waitFor(() =>
    expect(within(region).getByRole('table')).toHaveAttribute(
      'aria-busy',
      'true',
    ),
  );
  expect(screen.getByText('Accepted run')).toBeVisible();
  expect(screen.queryByText('Loading executions...')).not.toBeInTheDocument();
  expect(button).toHaveFocus();
  fireEvent.click(button);
  await screen.findByText('Accepted run');
  await act(async () => finish(result('Stale run')));
  expect(screen.queryByText('Stale run')).not.toBeInTheDocument();
  expect(
    within(region).getByRole('columnheader', { name: 'Status' }),
  ).toHaveAttribute('aria-sort', 'descending');
});
it('resets execution sort when the job identity changes', async () => {
  open();
  await screen.findByText('Accepted run');
  fireEvent.click(screen.getByRole('button', { name: 'Exit' }));
  await waitFor(() =>
    expect(api.jobs.executions).toHaveBeenLastCalledWith(42, {
      limit: 10,
      offset: 0,
      sort: 'exit_asc',
    }),
  );
  fireEvent.click(screen.getByRole('link', { name: 'Other job' }));
  await screen.findByRole('heading', { name: 'Job 43' });
  await waitFor(() =>
    expect(api.jobs.executions).toHaveBeenLastCalledWith(43, {
      limit: 10,
      offset: 0,
    }),
  );
});
