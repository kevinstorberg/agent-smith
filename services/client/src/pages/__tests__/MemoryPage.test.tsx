import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, act } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { MemoryPage } from '../MemoryPage';

vi.mock('../../api', () => ({
  api: {
    memory: {
      list: vi.fn(),
      search: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
    },
  },
}));

import { api } from '../../api';

const mockList = api.memory.list as ReturnType<typeof vi.fn>;
const mockSearch = api.memory.search as ReturnType<typeof vi.fn>;
const mockUpdate = api.memory.update as ReturnType<typeof vi.fn>;
const mockRemove = api.memory.remove as ReturnType<typeof vi.fn>;

const fakeMemories = [
  {
    id: 'mem-1',
    content: 'First memory content',
    repo: 'agent-smith',
    tags: ['architecture', 'convention'],
    created_at: '2026-01-10T08:00:00Z',
  },
  {
    id: 'mem-2',
    content: 'Second memory content',
    repo: undefined,
    tags: undefined,
    created_at: '2026-02-15T12:00:00Z',
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue({ items: fakeMemories, total: 2 });
  mockSearch.mockResolvedValue({ items: [], total: 0 });
  mockUpdate.mockResolvedValue(fakeMemories[0]);
  mockRemove.mockResolvedValue({ deleted: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('MemoryPage', () => {
  it('loads and displays memory items in list mode', async () => {
    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    expect(screen.getByText('Second memory content')).toBeInTheDocument();
    expect(screen.getByText('agent-smith')).toBeInTheDocument();
    expect(screen.getByText('architecture')).toBeInTheDocument();
    expect(screen.getByText('convention')).toBeInTheDocument();
  });

  it('shows empty state when no memories exist', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });

    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('No memories yet')).toBeInTheDocument();
    });
  });

  it('polls the current memory list every 15 seconds and stops after unmount', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { unmount } = renderWithProviders(<MemoryPage />);

    await waitFor(() => expect(screen.getByText('First memory content')).toBeInTheDocument());
    mockList.mockClear();

    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
    });

    expect(mockList).toHaveBeenCalledWith(expect.objectContaining({ limit: 10, offset: 0 }));

    unmount();
    mockList.mockClear();
    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
    });

    expect(mockList).not.toHaveBeenCalled();
  });

  it('does not poll while inline editing a memory', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<MemoryPage />);

    await waitFor(() => expect(screen.getByText('First memory content')).toBeInTheDocument());
    fireEvent.click(screen.getAllByText('Edit')[0]);
    mockList.mockClear();

    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
    });

    expect(mockList).not.toHaveBeenCalled();
  });

  it('shows filter-specific empty state when filters return zero', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });

    renderWithProviders(<MemoryPage />);

    const repoInput = await screen.findByPlaceholderText('Filter by repo');
    fireEvent.change(repoInput, { target: { value: 'no-such-repo' } });

    await waitFor(() => {
      expect(screen.getByText('No memories match the current filters')).toBeInTheDocument();
    });
    expect(screen.queryByText('No memories yet')).not.toBeInTheDocument();
  });

  it('performs search and shows search empty state', async () => {
    mockSearch.mockResolvedValue({ items: [], total: 0 });

    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText('Semantic search...');
    fireEvent.change(searchInput, { target: { value: 'nonexistent' } });
    fireEvent.click(screen.getByText('Search'));

    await waitFor(() => {
      expect(screen.getByText('No results found')).toBeInTheDocument();
    });

    expect(mockSearch).toHaveBeenCalledWith('nonexistent', expect.objectContaining({ limit: 10, offset: 0, sort: 'relevance' }));
  });

  it('renders repo, tags, and sort controls', async () => {
    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    expect(screen.getByPlaceholderText('Filter by repo')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Filter by tags (comma-separated)')).toBeInTheDocument();
    expect(screen.getByLabelText('Sort')).toBeInTheDocument();
  });

  it('typing in tags input refetches with tags param', async () => {
    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    const tagsInput = screen.getByPlaceholderText('Filter by tags (comma-separated)');
    fireEvent.change(tagsInput, { target: { value: 'a, b' } });

    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith(expect.objectContaining({ tags: ['a', 'b'], offset: 0 }));
    });
  });

  it('changing sort dropdown refetches with sort and resets offset', async () => {
    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    const sortSelect = screen.getByLabelText('Sort');
    fireEvent.change(sortSelect, { target: { value: 'created_at_asc' } });

    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith(expect.objectContaining({ sort: 'created_at_asc', offset: 0 }));
    });
  });

  it('shows Relevance sort option only in search mode', async () => {
    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    const sortSelect = screen.getByLabelText('Sort') as HTMLSelectElement;
    const optionValues = Array.from(sortSelect.options).map(o => o.value);
    expect(optionValues).not.toContain('relevance');

    const searchInput = screen.getByPlaceholderText('Semantic search...');
    fireEvent.change(searchInput, { target: { value: 'q' } });
    fireEvent.click(screen.getByText('Search'));

    await waitFor(() => {
      const updated = Array.from((screen.getByLabelText('Sort') as HTMLSelectElement).options).map(o => o.value);
      expect(updated).toContain('relevance');
    });
  });

  it('triggers search on Enter key', async () => {
    mockSearch.mockResolvedValue({ items: [fakeMemories[0]], total: 1 });

    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText('Semantic search...');
    fireEvent.change(searchInput, { target: { value: 'architecture' } });
    fireEvent.keyDown(searchInput, { key: 'Enter' });

    await waitFor(() => {
      expect(mockSearch).toHaveBeenCalled();
    });
  });

  it('clears search and returns to list mode', async () => {
    mockSearch.mockResolvedValue({ items: [fakeMemories[0]], total: 1 });

    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText('Semantic search...');
    fireEvent.change(searchInput, { target: { value: 'test' } });
    fireEvent.click(screen.getByText('Search'));

    await waitFor(() => {
      expect(screen.getByText('Clear')).toBeInTheDocument();
    });

    mockList.mockResolvedValue({ items: fakeMemories, total: 2 });

    fireEvent.click(screen.getByText('Clear'));

    await waitFor(() => {
      expect(screen.getByText('Second memory content')).toBeInTheDocument();
    });
  });

  it('opens inline edit with pre-filled values', async () => {
    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    const editButtons = screen.getAllByText('Edit');
    fireEvent.click(editButtons[0]);

    const textarea = screen.getByDisplayValue('First memory content');
    expect(textarea).toBeInTheDocument();

    const repoInput = screen.getByDisplayValue('agent-smith');
    expect(repoInput).toBeInTheDocument();

    const tagsInput = screen.getByDisplayValue('architecture, convention');
    expect(tagsInput).toBeInTheDocument();
  });

  it('saves edited memory with parsed tags', async () => {
    mockList.mockResolvedValue({ items: fakeMemories, total: 2 });
    mockUpdate.mockResolvedValue({ ...fakeMemories[0], content: 'Updated content' });

    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    const editButtons = screen.getAllByText('Edit');
    fireEvent.click(editButtons[0]);

    const textarea = screen.getByDisplayValue('First memory content');
    fireEvent.change(textarea, { target: { value: 'Updated content' } });

    const tagsInput = screen.getByDisplayValue('architecture, convention');
    fireEvent.change(tagsInput, { target: { value: 'new-tag, another' } });

    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith('mem-1', {
        content: 'Updated content',
        repo: 'agent-smith',
        tags: ['new-tag', 'another'],
      });
    });
  });

  it('cancels edit without saving', async () => {
    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    const editButtons = screen.getAllByText('Edit');
    fireEvent.click(editButtons[0]);

    expect(screen.getByDisplayValue('First memory content')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Cancel'));

    expect(screen.queryByDisplayValue('First memory content')).not.toBeInTheDocument();
    expect(mockUpdate).not.toHaveBeenCalled();
  });

  it('uses two-step delete confirmation', async () => {
    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByText('Delete');
    fireEvent.click(deleteButtons[0]);

    expect(screen.getByText('Delete?')).toBeInTheDocument();
    expect(screen.getByText('Yes')).toBeInTheDocument();
    expect(screen.getByText('No')).toBeInTheDocument();

    expect(mockRemove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText('Yes'));

    await waitFor(() => {
      expect(mockRemove).toHaveBeenCalledWith('mem-1');
    });
  });

  it('cancels two-step delete when No is clicked', async () => {
    renderWithProviders(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText('First memory content')).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByText('Delete');
    fireEvent.click(deleteButtons[0]);

    expect(screen.getByText('Delete?')).toBeInTheDocument();

    fireEvent.click(screen.getByText('No'));

    expect(screen.queryByText('Delete?')).not.toBeInTheDocument();
    expect(mockRemove).not.toHaveBeenCalled();
  });
});
