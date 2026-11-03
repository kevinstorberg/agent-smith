import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { api } from '../../api';
import type { Job, Paginated } from '../../api';
import { JobsIndexPage } from '../JobsIndexPage';

vi.mock('../../api', () => ({ api: { jobs: { list: vi.fn(), setScheduling: vi.fn() } } }));

const list = vi.mocked(api.jobs.list);
const job = (name: string): Job => ({ id: 1, name, schedule_enabled: true, schedule_config: { hours: 1 },
  input_params: {}, description: null, version: 1, created_at: '', updated_at: '' });

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  list.mockResolvedValue({ items: [job('Current job')], total: 25 });
});

afterEach(() => vi.useRealTimers());

describe('Jobs filters with real pagination', () => {
  it('debounces search and sends every changed criterion at offset zero', async () => {
    renderWithProviders(<JobsIndexPage />);
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await act(async () => {});
    expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }));
    list.mockClear();

    const input = screen.getByPlaceholderText('Search jobs...');
    input.focus();
    fireEvent.change(input, { target: { value: 'back' } });
    await act(async () => { vi.advanceTimersByTime(299); });
    expect(list).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'back', offset: 0 }));
    expect(list.mock.calls.some(([params]) => params?.q === 'back' && params.offset !== 0)).toBe(false);
    expect(input).toHaveFocus();

    fireEvent.change(screen.getByRole('combobox', { name: 'Scheduling' }), { target: { value: 'false' } });
    await act(async () => {});
    expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'back', schedule_enabled: false, offset: 0 }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort jobs' }), { target: { value: 'name' } });
    await act(async () => {});
    expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'name', offset: 0 }));

    fireEvent.change(input, { target: { value: '' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ q: undefined, schedule_enabled: false, sort: 'name' }));
  });

  it('keeps controls mounted and ignores an old response after criteria change', async () => {
    let finishOld!: (result: Paginated<Job>) => void;
    list.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }));
    renderWithProviders(<JobsIndexPage />);
    const input = screen.getByPlaceholderText('Search jobs...');
    fireEvent.change(input, { target: { value: 'current' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(screen.getByText('Current job')).toBeInTheDocument();
    await act(async () => { finishOld({ items: [job('Stale job')], total: 1 }); });
    expect(screen.queryByText('Stale job')).not.toBeInTheDocument();
    expect(screen.getByText('Current job')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search jobs...')).toBe(input);
  });

  it('hides previous matches and paging when changed criteria fail', async () => {
    renderWithProviders(<JobsIndexPage />);
    await act(async () => {});
    expect(screen.getByText('Current job')).toBeInTheDocument();
    list.mockRejectedValueOnce(new Error('Unavailable'));
    fireEvent.change(screen.getByPlaceholderText('Search jobs...'), { target: { value: 'unavailable' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(screen.queryByText('Current job')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument();
    expect(screen.queryByText('No jobs found')).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search jobs...')).toHaveValue('unavailable');
  });
});
