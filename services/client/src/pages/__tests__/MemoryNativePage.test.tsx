import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../api';
import type { MemoryConfig, MemoryCursorPage } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { defaultView, mergeViewCookie } from '../../utils/viewPreferences';
import { MemoryPage } from '../MemoryPage';
import { cursorMemoryConfig } from './memoryFixture';

vi.mock('../../api', () => ({
  api: {
    memory: {
      config: vi.fn(),
      list: vi.fn(),
      search: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
    },
  },
}));

const page = (
  content: string,
  next: string | null = null,
): MemoryCursorPage => ({
  mode: 'cursor',
  items: [{ id: content, content }],
  next_cursor: next,
  order: 'id_asc',
});

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.mocked(api.memory.config).mockResolvedValue(cursorMemoryConfig);
  vi.mocked(api.memory.list).mockResolvedValue(
    page('First native memory', 'next-token'),
  );
  vi.mocked(api.memory.search).mockResolvedValue({
    items: [{ id: 'search', content: 'Semantic memory' }],
    total: 50,
  });
});
afterEach(() => vi.useRealTimers());

describe('native Memory browsing', () => {
  it('waits for local capabilities before any data request', async () => {
    let resolve!: (value: MemoryConfig) => void;
    vi.mocked(api.memory.config).mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
    renderWithProviders(<MemoryPage />, { initialEntries: ['/memory'] });
    expect(api.memory.list).not.toHaveBeenCalled();
    expect(api.memory.search).not.toHaveBeenCalled();
    await act(async () => {
      resolve(cursorMemoryConfig);
    });
    expect(await screen.findByText('First native memory')).toBeInTheDocument();
    expect(api.memory.config).toHaveBeenCalledTimes(1);
    expect(api.memory.list).toHaveBeenCalledExactlyOnceWith({ limit: 10 });
  });

  it('retries failed capabilities without requesting data under unknown capabilities', async () => {
    vi.mocked(api.memory.config).mockRejectedValueOnce(
      new Error('private config error'),
    );
    renderWithProviders(<MemoryPage />, { initialEntries: ['/memory'] });
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load memories.',
    );
    expect(screen.queryByText('private config error')).not.toBeInTheDocument();
    expect(api.memory.list).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('First native memory')).toBeInTheDocument();
    expect(api.memory.config).toHaveBeenCalledTimes(2);
    expect(api.memory.list).toHaveBeenCalledTimes(1);
  });

  it('ignores saved native offset, date sort and filters without traversing or claiming totals', async () => {
    document.cookie = mergeViewCookie('', 'memory', {
      ...defaultView('memory'),
      repo: 'saved-repo',
      tags: 'saved-tag',
      meeting_only: true,
      listSort: 'updated_at_desc',
      offset: 50,
    });
    renderWithProviders(<MemoryPage />, { initialEntries: ['/memory'] });
    await screen.findByText('First native memory');
    expect(api.memory.list).toHaveBeenCalledExactlyOnceWith({ limit: 10 });
    expect(screen.getByText('Memory ID order')).toBeInTheDocument();
    expect(screen.queryByLabelText('Repository')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Tags')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Sort')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('checkbox', { name: 'Meetings only' }),
    ).not.toBeInTheDocument();
    expect(screen.getByText('Page 1')).toBeInTheDocument();
    expect(screen.queryByText(/Showing .* of /)).not.toBeInTheDocument();
    expect(screen.queryByText(/Page 1 of/)).not.toBeInTheDocument();
  });

  it('navigates and refreshes one requested page, resets page size, and never polls', async () => {
    vi.useFakeTimers();
    vi.mocked(api.memory.list)
      .mockResolvedValueOnce(page('First native memory', 'next-token'))
      .mockResolvedValueOnce(page('Second native memory'))
      .mockResolvedValueOnce(page('Refreshed second memory'))
      .mockResolvedValue(page('New first memory'));
    await act(async () => {
      renderWithProviders(<MemoryPage />, { initialEntries: ['/memory'] });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    });
    expect(screen.getByText('Page 2')).toBeInTheDocument();
    expect(api.memory.list).toHaveBeenLastCalledWith({
      limit: 10,
      cursor: 'next-token',
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    });
    expect(api.memory.list).toHaveBeenCalledTimes(3);
    expect(api.memory.list).toHaveBeenLastCalledWith({
      limit: 10,
      cursor: 'next-token',
    });
    await act(async () => {
      fireEvent.change(screen.getByLabelText('Rows per page'), {
        target: { value: '25' },
      });
    });
    expect(api.memory.list).toHaveBeenCalledTimes(4);
    expect(api.memory.list).toHaveBeenLastCalledWith({ limit: 25 });
    expect(screen.getByText('Page 1')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(api.memory.list).toHaveBeenCalledTimes(4);
  });

  it('retains a successful page after failed navigation and offers a first-page restart', async () => {
    vi.mocked(api.memory.list)
      .mockResolvedValueOnce(page('First native memory', 'expired-token'))
      .mockRejectedValueOnce(new Error('private provider diagnostic'))
      .mockResolvedValueOnce(page('Restarted native memory'));
    renderWithProviders(<MemoryPage />, { initialEntries: ['/memory'] });
    await screen.findByText('First native memory');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByRole('alert');
    expect(screen.getByText('First native memory')).toBeInTheDocument();
    expect(screen.getByText('Page 1')).toBeInTheDocument();
    expect(
      screen.queryByText('private provider diagnostic'),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Restart from first page' }),
    );
    await screen.findByText('Restarted native memory');
    expect(api.memory.list).toHaveBeenCalledTimes(3);
    expect(api.memory.list).toHaveBeenLastCalledWith({ limit: 10 });
  });

  it('keeps Next available on an empty provider page without claiming the memory store is empty', async () => {
    let resolve!: (value: MemoryCursorPage) => void;
    vi.mocked(api.memory.list).mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
    renderWithProviders(<MemoryPage />, { initialEntries: ['/memory'] });
    await waitFor(() => expect(api.memory.list).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByText('No memories on this page'),
    ).not.toBeInTheDocument();
    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    await act(async () => {
      resolve({ ...page('', 'next-token'), items: [] });
    });
    expect(
      await screen.findByText('No memories on this page'),
    ).toBeInTheDocument();
    expect(screen.queryByText('No memories yet')).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled(),
    );
    expect(api.memory.list).toHaveBeenCalledTimes(1);
  });

  it('preserves search filters and numeric top-50 pagination, then returns to a fresh native page', async () => {
    document.cookie = mergeViewCookie('', 'memory', {
      ...defaultView('memory'),
      repo: 'saved-repo',
      tags: 'saved-tag',
      meeting_only: true,
    });
    renderWithProviders(<MemoryPage />, { initialEntries: ['/memory'] });
    await screen.findByText('First native memory');
    fireEvent.change(screen.getByRole('textbox', { name: 'Search memories' }), {
      target: { value: 'release' },
    });
    await screen.findByText('Semantic memory');
    expect(screen.getByLabelText('Repository')).toHaveValue('saved-repo');
    expect(screen.getByLabelText('Tags')).toHaveValue('saved-tag');
    expect(
      screen.getByText(
        'Search results are limited to the top 50 semantic matches.',
      ),
    ).toBeInTheDocument();
    expect(api.memory.search).toHaveBeenLastCalledWith('release', {
      limit: 10,
      offset: 0,
      repo: 'saved-repo',
      tags: ['saved-tag'],
      meeting_only: true,
      sort: 'relevance',
    });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(api.memory.search).toHaveBeenLastCalledWith(
        'release',
        expect.objectContaining({ offset: 10 }),
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await screen.findByText('First native memory');
    expect(api.memory.list).toHaveBeenCalledTimes(2);
    expect(api.memory.list).toHaveBeenLastCalledWith({ limit: 10 });
    expect(screen.getByText('Page 1')).toBeInTheDocument();
  });
});
