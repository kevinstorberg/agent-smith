import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, act } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { HarnessIndexPage } from '../HarnessIndexPage';

vi.mock('@hello-pangea/dnd', () => ({
  DragDropContext: ({ children }: any) => <>{children}</>,
  Droppable: ({ children }: any) => <div>{children({ innerRef: () => {}, droppableProps: {}, placeholder: null })}</div>,
  Draggable: ({ children }: any) => <div>{children({ innerRef: () => {}, draggableProps: { style: {} }, dragHandleProps: {} }, { isDragging: false })}</div>,
}));

const mockNavigate = vi.fn();
vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const { mockList, mockUpdateMetadata, mockReorder } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockUpdateMetadata: vi.fn(),
  mockReorder: vi.fn(),
}));

vi.mock('../../api', () => ({
  api: {
    harness: {
      items: {
        list: (...args: any[]) => mockList(...args),
        updateMetadata: (...args: any[]) => mockUpdateMetadata(...args),
        reorder: (...args: any[]) => mockReorder(...args),
      },
    },
  },
}));

function makeItem(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: 'test_rule',
    project: null,
    agents: ['claude'],
    content: { body: '# Rule', metadata: {} },
    sort_key: 0,
    enabled: true,
    clone_as_skill: false,
    version: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    configs: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue({ items: [makeItem()], total: 1 });
  mockUpdateMetadata.mockResolvedValue({});
});

afterEach(() => {
  vi.useRealTimers();
});

describe('HarnessIndexPage', () => {
  it('renders table with item data', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />);

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    expect(screen.getByText('test_rule')).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
    expect(screen.getByText('claude')).toBeInTheDocument();
  });

  it('shows the correct type heading', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />);

    await waitFor(() => {
      expect(screen.getByText('Rules')).toBeInTheDocument();
    });
  });

  it('toggles enabled state on checkbox click', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />);

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[0]);

    await waitFor(() => {
      expect(mockUpdateMetadata).toHaveBeenCalledWith('rule', 1, { enabled: false });
    });
  });

  it('shows clone_as_skill column only for rules', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />);

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    expect(screen.getByText('Skill Clone')).toBeInTheDocument();
  });

  it('hides clone_as_skill column for non-rule types', async () => {
    mockList.mockResolvedValue({ items: [makeItem({ id: 2, name: 'test_tool' })], total: 1 });
    renderWithProviders(<HarnessIndexPage type="tool" />);

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    expect(screen.queryByText('Skill Clone')).not.toBeInTheDocument();
  });

  it('navigates to detail page on row click', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />);

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('test_rule'));
    expect(mockNavigate).toHaveBeenCalledWith('/harness/rule/1');
  });

  it('navigates to create page on new button click', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />);

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('+ New Rule'));
    expect(mockNavigate).toHaveBeenCalledWith('/harness/rule/new');
  });

  it('shows empty state when no items found', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<HarnessIndexPage type="rule" />);

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    expect(screen.getByText('No rules found')).toBeInTheDocument();
  });

  it('debounces name filter input', async () => {
    vi.useFakeTimers();
    renderWithProviders(<HarnessIndexPage type="rule" />);

    // Wait for initial load
    await act(async () => {
      vi.advanceTimersByTime(10);
    });

    mockList.mockClear();

    const nameInput = screen.getByPlaceholderText('Search by name...');

    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'search_term' } });
    });

    // Should not have called immediately
    expect(mockList).not.toHaveBeenCalled();

    // Advance past debounce
    await act(async () => {
      vi.advanceTimersByTime(350);
    });

    expect(mockList).toHaveBeenCalledWith(
      'rule',
      expect.objectContaining({ name: 'search_term' }),
    );
  });
});
