import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import type { Job } from '../../api';
import { jobFixture } from '../../pages/__tests__/jobFixture';
import { JobScheduleButton } from '../JobScheduleButton';

vi.mock('../../api', () => ({ api: { jobs: { setScheduling: vi.fn() } } }));
import { api } from '../../api';
const update = vi.mocked(api.jobs.setScheduling);
beforeEach(() => { vi.clearAllMocks(); update.mockResolvedValue({ ...jobFixture, schedule_enabled: false }); });

it('captures one absolute job/flag write and keeps the status unchanged until acknowledged', async () => {
  let finish!: (job: Job) => void;
  update.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const changed = vi.fn();
  renderWithProviders(<JobScheduleButton job={jobFixture} onChanged={changed} />);
  const button = screen.getByRole('button', { name: 'Pause automatic runs for Meeting imports' });
  fireEvent.click(button); fireEvent.click(button);
  expect(update).toHaveBeenCalledTimes(1);
  expect(update).toHaveBeenCalledWith(42, { schedule_enabled: false });
  expect(button).toBeDisabled(); expect(button).toHaveTextContent('Saving...');
  expect(changed).not.toHaveBeenCalled();
  const acknowledged = { ...jobFixture, schedule_enabled: false, version: 2 };
  await act(async () => finish(acknowledged));
  expect(changed).toHaveBeenCalledExactlyOnceWith(acknowledged);
});

it('resumes a paused job without submitting its definition or device configurations', async () => {
  update.mockResolvedValueOnce(jobFixture);
  renderWithProviders(<JobScheduleButton job={{ ...jobFixture, schedule_enabled: false }} onChanged={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Resume automatic runs for Meeting imports' }));
  await waitFor(() => expect(update).toHaveBeenCalledWith(42, { schedule_enabled: true }));
});

it('keeps mouse and keyboard interactions from activating its clickable parent', async () => {
  const navigate = vi.fn();
  renderWithProviders(<div onClick={navigate} onKeyDown={navigate}>
    <JobScheduleButton job={jobFixture} onChanged={vi.fn()} /></div>);
  const button = screen.getByRole('button');
  fireEvent.keyDown(button, { key: 'Enter' }); fireEvent.keyDown(button, { key: ' ' }); fireEvent.click(button);
  await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
  expect(navigate).not.toHaveBeenCalled();
});

it('reports failure without claiming a pause and retries the same desired value', async () => {
  update.mockRejectedValueOnce(new Error('PRIVATE_DIAGNOSTIC'));
  const changed = vi.fn();
  renderWithProviders(<JobScheduleButton job={jobFixture} onChanged={changed} />);
  fireEvent.click(screen.getByRole('button'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not change automatic runs.');
  expect(screen.queryByText('PRIVATE_DIAGNOSTIC')).not.toBeInTheDocument();
  expect(changed).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Pause automatic runs for Meeting imports' }));
  await waitFor(() => expect(update).toHaveBeenCalledTimes(2));
  expect(update.mock.calls.map(call => call[1])).toEqual([{ schedule_enabled: false }, { schedule_enabled: false }]);
});

it('ignores a delayed acknowledgement after the source job is unmounted', async () => {
  let finish!: (job: Job) => void;
  update.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const changed = vi.fn();
  const view = renderWithProviders(<JobScheduleButton key={42} job={jobFixture} onChanged={changed} />);
  fireEvent.click(screen.getByRole('button'));
  view.rerender(<JobScheduleButton key={43} job={{ ...jobFixture, id: 43, name: 'Personas' }} onChanged={changed} />);
  await act(async () => finish({ ...jobFixture, schedule_enabled: false }));
  expect(changed).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Pause automatic runs for Personas' })).toBeEnabled();
});

it('rejects an acknowledgement for a different job', async () => {
  update.mockResolvedValueOnce({ ...jobFixture, id: 43, schedule_enabled: false });
  const changed = vi.fn();
  renderWithProviders(<JobScheduleButton job={jobFixture} onChanged={changed} />);
  fireEvent.click(screen.getByRole('button'));
  await screen.findByRole('alert'); expect(changed).not.toHaveBeenCalled();
});
