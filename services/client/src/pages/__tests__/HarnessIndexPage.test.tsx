import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  screen,
  fireEvent,
  waitFor,
  act,
  within,
} from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { HarnessIndexPage } from '../HarnessIndexPage';
import {
  defaultView,
  harnessViewKey,
  mergeViewCookie,
} from '../../utils/viewPreferences';

const drag = vi.hoisted(() => ({ start: vi.fn(), end: vi.fn() }));
vi.mock('@hello-pangea/dnd', () => ({
  DragDropContext: ({ children, onBeforeDragStart, onDragEnd }: any) => {
    drag.start = onBeforeDragStart;
    drag.end = onDragEnd;
    return <>{children}</>;
  },
  Droppable: ({ children, isDropDisabled }: any) => (
    <div data-testid="harness-drop-zone" data-disabled={String(isDropDisabled)}>
      {children({ innerRef: () => {}, droppableProps: {}, placeholder: null })}
    </div>
  ),
  Draggable: ({ children }: any) => (
    <div>
      {children(
        {
          innerRef: () => {},
          draggableProps: { style: {} },
          dragHandleProps: {},
        },
        { isDragging: false },
      )}
    </div>
  ),
}));

const mockNavigate = vi.fn();
vi.mock('react-router', async () => {
  const actual =
    await vi.importActual<typeof import('react-router')>('react-router');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const { mockList, mockUpdateMetadata, mockReorder, mockMove } = vi.hoisted(
  () => ({
    mockList: vi.fn(),
    mockUpdateMetadata: vi.fn(),
    mockReorder: vi.fn(),
    mockMove: vi.fn(),
  }),
);

vi.mock('../../api', () => ({
  api: {
    harness: {
      items: {
        list: (...args: any[]) => mockList(...args),
        updateMetadata: (...args: any[]) => mockUpdateMetadata(...args),
        reorder: (...args: any[]) => mockReorder(...args),
        move: (...args: any[]) => mockMove(...args),
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
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.resetAllMocks();
  mockList.mockResolvedValue({ items: [makeItem()], total: 1 });
  mockUpdateMetadata.mockResolvedValue({});
  mockMove.mockResolvedValue({});
});

afterEach(() => {
  vi.useRealTimers();
});

describe('HarnessIndexPage', () => {
  it.each(['rule', 'skill', 'tool', 'hook', 'agent'])(
    'silently polls the current %s page at 15 seconds and stops on unmount',
    async (type) => {
      vi.useFakeTimers();
      const key = harnessViewKey(type);
      document.cookie = mergeViewCookie('', key, {
        ...defaultView(key),
        name: 'visible',
        project: 'docs',
        sort: 'updated',
        limit: 25,
        offset: 25,
      });
      mockList.mockResolvedValue({ items: [makeItem()], total: 100 });
      let view!: ReturnType<typeof renderWithProviders>;
      await act(async () => {
        view = renderWithProviders(<HarnessIndexPage type={type} />, {
          initialEntries: [
            `/harness/${{ rule: 'rules', skill: 'skills', tool: 'tools', hook: 'hooks', agent: 'agents' }[type]}`,
          ],
        });
      });
      expect(mockList).toHaveBeenCalledExactlyOnceWith(type, {
        limit: 25,
        offset: 25,
        name: 'visible',
        project: 'docs',
        sort: 'updated',
      });
      let finish!: (value: unknown) => void;
      mockList.mockClear().mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve;
        }),
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(14_999);
      });
      expect(mockList).not.toHaveBeenCalled();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(mockList).toHaveBeenCalledExactlyOnceWith(type, {
        limit: 25,
        offset: 25,
        name: 'visible',
        project: 'docs',
        sort: 'updated',
      });
      expect(screen.getByText('test_rule')).toBeVisible();
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(mockList).toHaveBeenCalledTimes(1);
      await act(async () => {
        finish({ items: [makeItem({ name: 'Agent update' })], total: 100 });
      });
      expect(screen.getByText('Agent update')).toBeVisible();
      view.unmount();
      mockList.mockClear();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      expect(mockList).not.toHaveBeenCalled();
    },
  );

  it('pauses polling during a drag and its save and recovery read', async () => {
    vi.useFakeTimers();
    const rows = [makeItem(), makeItem({ id: 2, name: 'second_rule' })];
    mockList.mockResolvedValue({ items: rows, total: 2 });
    let finishWrite!: (value: unknown) => void;
    let finishRead!: (value: unknown) => void;
    mockMove.mockReturnValueOnce(
      new Promise((resolve) => {
        finishWrite = resolve;
      }),
    );
    await act(async () => {
      renderWithProviders(<HarnessIndexPage type="rule" />, {
        initialEntries: ['/harness/rules'],
      });
    });
    act(() => {
      drag.start();
    });
    mockList.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(mockList).not.toHaveBeenCalled();
    let end!: Promise<void>;
    act(() => {
      end = drag.end({
        draggableId: '1',
        reason: 'DROP',
        source: { index: 0 },
        destination: { index: 1 },
      });
    });
    expect(mockMove).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(mockList).not.toHaveBeenCalled();
    mockList.mockReturnValueOnce(
      new Promise((resolve) => {
        finishRead = resolve;
      }),
    );
    await act(async () => {
      finishWrite({});
    });
    expect(mockList).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(mockList).toHaveBeenCalledTimes(1);
    await act(async () => {
      finishRead({ items: rows, total: 2 });
      await end;
    });
    mockList.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('rejects an old poll after filters change and waits for settled criteria', async () => {
    vi.useFakeTimers();
    await act(async () => {
      renderWithProviders(<HarnessIndexPage type="rule" />, {
        initialEntries: ['/harness/rules'],
      });
    });
    let finish!: (value: unknown) => void;
    mockList.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    mockList.mockResolvedValue({
      items: [makeItem({ name: 'current filtered item' })],
      total: 1,
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'current' },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(screen.getByText('current filtered item')).toBeVisible();
    await act(async () => {
      finish({ items: [makeItem({ name: 'stale poll' })], total: 1 });
    });
    expect(screen.queryByText('stale poll')).not.toBeInTheDocument();
    mockList.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(mockList).toHaveBeenCalledExactlyOnceWith(
      'rule',
      expect.objectContaining({ name: 'current', offset: 0 }),
    );
  });

  it.each(['enabled', 'clone_as_skill'] as const)(
    'refreshes server order after changing %s using the current filter and page',
    async (field) => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const items = [makeItem(), makeItem({ id: 2, name: 'another_rule' })];
      mockList.mockResolvedValue({ items, total: 25 });
      let finish!: (value: unknown) => void;
      mockUpdateMetadata.mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve;
        }),
      );
      renderWithProviders(<HarnessIndexPage type="rule" />, {
        initialEntries: ['/harness/rules'],
      });
      await screen.findByText('test_rule');
      fireEvent.click(screen.getByRole('button', { name: 'Updated' }));
      await waitFor(() =>
        expect(mockList).toHaveBeenLastCalledWith(
          'rule',
          expect.objectContaining({ sort: 'updated' }),
        ),
      );
      fireEvent.change(screen.getByPlaceholderText('Filter by project...'), {
        target: { value: 'current-project' },
      });
      await act(async () => {
        vi.advanceTimersByTime(300);
      });
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      await waitFor(() =>
        expect(mockList).toHaveBeenLastCalledWith(
          'rule',
          expect.objectContaining({ offset: 10 }),
        ),
      );
      const row = screen.getByRole('row', { name: /another_rule/ });
      await waitFor(() =>
        expect(within(row).getAllByRole('checkbox')[0]).toBeEnabled(),
      );
      fireEvent.click(
        within(row).getAllByRole('checkbox')[field === 'enabled' ? 0 : 1],
      );
      expect(mockUpdateMetadata).toHaveBeenCalledWith('rule', 2, {
        [field]: field === 'clone_as_skill',
      });
      expect(
        screen.getByPlaceholderText('Filter by project...'),
      ).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
      screen
        .getAllByRole('columnheader')
        .forEach((header) =>
          expect(within(header).getByRole('button')).toBeDisabled(),
        );
      mockList
        .mockResolvedValue({ items: [items[1], items[0]], total: 25 })
        .mockClear();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      expect(mockList).not.toHaveBeenCalled();
      await act(async () => {
        finish({});
      });
      expect(mockList).toHaveBeenCalledTimes(1);
      expect(mockList).toHaveBeenCalledWith(
        'rule',
        expect.objectContaining({
          offset: 10,
          project: 'current-project',
          sort: 'updated',
        }),
      );
      const rows = within(screen.getByTestId('harness-drop-zone'))
        .getAllByRole('row')
        .filter((row) => row.classList.contains('harness-list-row'));
      expect(rows[0]).toHaveTextContent('another_rule');
      expect(rows[1]).toHaveTextContent('test_rule');
    },
  );

  it('keeps search, project filter and sort available while loading and with no resources', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });
    for (const name of ['Search', 'Project scope'])
      expect(screen.getByRole('textbox', { name })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Order' })).toBeVisible();
    expect(
      screen.queryByRole('combobox', { name: 'Sort' }),
    ).not.toBeInTheDocument();
    await screen.findByText('No rules found');
    expect(screen.getByRole('columnheader', { name: 'Order' })).toHaveAttribute(
      'aria-sort',
      'ascending',
    );
    expect(mockList).toHaveBeenCalledWith(
      'rule',
      expect.objectContaining({ sort: 'manual' }),
    );
  });

  it('applies sort on the server from page zero and keeps a single visible row non-draggable', async () => {
    mockList.mockResolvedValue({ items: [makeItem()], total: 25 });
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });
    await screen.findByText('test_rule');
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute(
      'data-disabled',
      'true',
    );
    await act(async () => {
      await drag.end({ source: { index: 0 }, destination: { index: 1 } });
    });
    expect(mockReorder).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith(
        'rule',
        expect.objectContaining({ offset: 10 }),
      ),
    );
    mockList.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Name' }));
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    expect(mockList).toHaveBeenCalledWith(
      'rule',
      expect.objectContaining({ offset: 0, sort: 'name' }),
    );
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute(
      'data-disabled',
      'true',
    );
  });

  it('rejects a saved manual drag callback after sorting changes and restores full-list manual dragging', async () => {
    const items = [makeItem(), makeItem({ id: 2, name: 'another_rule' })];
    mockList.mockResolvedValue({ items, total: 2 });
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });
    await screen.findByText('test_rule');
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute(
      'data-disabled',
      'false',
    );
    const manualDrop = drag.end;
    fireEvent.click(screen.getByRole('button', { name: 'Updated' }));
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith(
        'rule',
        expect.objectContaining({ sort: 'updated' }),
      ),
    );
    await act(async () => {
      await manualDrop({ source: { index: 0 }, destination: { index: 1 } });
    });
    expect(mockReorder).not.toHaveBeenCalled();
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute(
      'data-disabled',
      'true',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Order' }));
    await waitFor(() =>
      expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute(
        'data-disabled',
        'false',
      ),
    );
    act(() => {
      drag.start();
    });
    await act(async () => {
      await drag.end({
        reason: 'DROP',
        draggableId: '1',
        source: { index: 0 },
        destination: { index: 1 },
      });
    });
    expect(mockMove).toHaveBeenCalledWith('rule', 1, {
      after_id: 2,
      expected_updated_at: items[0].updated_at,
      expected_anchor_updated_at: items[1].updated_at,
    });
    expect(mockReorder).not.toHaveBeenCalled();
  });

  it('labels retained rows and blocks stale drag callbacks while changed criteria refetch', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });
    await screen.findByText('test_rule');
    const input = screen.getByPlaceholderText('Search by name...');
    fireEvent.change(input, { target: { value: 'subset' } });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute(
      'data-disabled',
      'true',
    );
    const oldDrop = drag.end;
    let resolve!: (value: unknown) => void;
    mockList.mockReturnValueOnce(
      new Promise((complete) => {
        resolve = complete;
      }),
    );
    input.focus();
    fireEvent.change(input, { target: { value: '' } });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(
      screen.getByText(
        'Showing previous results. Reordering is unavailable until this view loads.',
      ),
    ).toBeVisible();
    expect(screen.getByText('test_rule')).toBeVisible();
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute(
      'data-disabled',
      'true',
    );
    screen
      .getAllByRole('checkbox')
      .forEach((checkbox) => expect(checkbox).toBeDisabled());
    expect(input).toHaveFocus();
    await act(async () => {
      await oldDrop({ source: { index: 0 }, destination: { index: 1 } });
    });
    expect(mockReorder).not.toHaveBeenCalled();
    await act(async () => {
      resolve({
        items: [makeItem(), makeItem({ id: 2, name: 'another_rule' })],
        total: 2,
      });
    });
    expect(screen.getByText('another_rule')).toBeInTheDocument();
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute(
      'data-disabled',
      'false',
    );
  });

  it('labels previous results after a retryable read error, blocks mutations, and preserves filter focus', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });
    await screen.findByText('test_rule');
    mockList.mockRejectedValueOnce(new Error('Private backend diagnostic'));
    const input = screen.getByPlaceholderText('Search by name...');
    input.focus();
    fireEvent.change(input, { target: { value: 'new criteria' } });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Could not load rules.',
    );
    expect(screen.getByText('test_rule')).toBeVisible();
    expect(
      screen.getByText(
        'Showing previous results. Reordering is unavailable until this view loads.',
      ),
    ).toBeVisible();
    expect(screen.queryByText('No rules found')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Private backend diagnostic'),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute(
      'data-disabled',
      'true',
    );
    screen
      .getAllByRole('checkbox')
      .forEach((checkbox) => expect(checkbox).toBeDisabled());
    expect(input).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('test_rule');
    expect(mockList).toHaveBeenLastCalledWith(
      'rule',
      expect.objectContaining({ name: 'new criteria', offset: 0 }),
    );
    expect(mockReorder).not.toHaveBeenCalled();
    expect(mockUpdateMetadata).not.toHaveBeenCalled();
  });

  it('renders table with item data', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    expect(screen.getByText('test_rule')).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
    expect(screen.getByText('claude')).toBeInTheDocument();
  });

  it('shows the correct type heading', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });

    await waitFor(() => {
      expect(screen.getByText('Rules')).toBeInTheDocument();
    });
  });

  it('toggles enabled state on checkbox click', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('checkbox', { name: 'Enable test_rule' }));

    await waitFor(() => {
      expect(mockUpdateMetadata).toHaveBeenCalledWith('rule', 1, {
        enabled: false,
      });
    });
  });

  it('shows clone_as_skill column only for rules', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    expect(screen.getByText('Skill Clone')).toBeInTheDocument();
  });

  it('hides clone_as_skill column for non-rule types', async () => {
    mockList.mockResolvedValue({
      items: [makeItem({ id: 2, name: 'test_tool' })],
      total: 1,
    });
    renderWithProviders(<HarnessIndexPage type="tool" />, {
      initialEntries: ['/harness/tools'],
    });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    expect(screen.queryByText('Skill Clone')).not.toBeInTheDocument();
  });

  it('navigates to detail page on row click', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('test_rule'));
    expect(mockNavigate).toHaveBeenCalledWith('/harness/rule/1');
  });

  it.each(['Enter', ' '])(
    'preserves row keyboard navigation with %j after adopting table roles',
    async (key) => {
      renderWithProviders(<HarnessIndexPage type="rule" />, {
        initialEntries: ['/harness/rules'],
      });
      await screen.findByText('test_rule');
      const row = screen.getByText('test_rule').closest('[role="row"]')!;
      fireEvent.keyDown(row, { key });
      expect(mockNavigate).toHaveBeenCalledExactlyOnceWith('/harness/rule/1');
    },
  );

  it('navigates to create page on new button click', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('+ New Rule'));
    expect(mockNavigate).toHaveBeenCalledWith('/harness/rule/new');
  });

  it('shows empty state when no items found', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });

    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });

    expect(screen.getByText('No rules found')).toBeInTheDocument();
  });

  it('debounces name filter input', async () => {
    vi.useFakeTimers();
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });

    // Wait for initial load
    await act(async () => {
      vi.advanceTimersByTime(10);
    });

    mockList.mockClear();

    const nameInput = screen.getByPlaceholderText('Search by name...');
    nameInput.focus();

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
    expect(screen.getByPlaceholderText('Search by name...')).toBe(nameInput);
    expect(nameInput).toHaveFocus();
  });
});

describe('Harness header sorting', () => {
  it.each(['rule', 'skill', 'tool', 'hook', 'agent'])(
    'exposes a valid %s table with sortable data headers and ordinary cells',
    async (type) => {
      renderWithProviders(<HarnessIndexPage type={type} />, {
        initialEntries: [`/harness/${type === 'rule' ? 'rules' : `${type}s`}`],
      });
      await screen.findByText('test_rule');
      const table = screen.getByRole('table');
      const expected = [
        'Order',
        'Name',
        'Project',
        'Enabled',
        ...(type === 'rule' ? ['Skill Clone'] : []),
        'Agents',
        'Configs',
        'Version',
        'Updated',
      ];
      expect(
        within(table)
          .getAllByRole('columnheader')
          .map((node) => node.textContent?.replace(/[↕▲▼]/g, '').trim()),
      ).toEqual(expected);
      for (const label of expected)
        expect(
          within(table).getByRole('columnheader', { name: label }),
        ).toContainElement(within(table).getByRole('button', { name: label }));
      const row = screen.getByText('test_rule').closest('[role="row"]')!;
      expect(within(row as HTMLElement).getAllByRole('cell')).toHaveLength(
        expected.length,
      );
      expect(within(table).getAllByRole('rowgroup')).toHaveLength(2);
      expect(screen.queryByRole('grid')).not.toBeInTheDocument();
      expect(
        screen.queryByRole('combobox', { name: 'Sort' }),
      ).not.toBeInTheDocument();
      expect(table).toHaveAttribute('aria-busy', 'false');
    },
  );

  it.each([
    ['Order', 'manual', 'manual_desc'],
    ['Name', 'name', 'name_desc'],
    ['Project', 'project_asc', 'project_desc'],
    ['Enabled', 'enabled_asc', 'enabled_desc'],
    ['Skill Clone', 'clone_as_skill_asc', 'clone_as_skill_desc'],
    ['Agents', 'agents_asc', 'agents_desc'],
    ['Configs', 'config_count_asc', 'config_count_desc'],
    ['Version', 'version_asc', 'version_desc'],
    ['Updated', 'updated_asc', 'updated'],
  ])(
    'toggles %s server order without metadata or rank writes',
    async (label, ascending, descending) => {
      renderWithProviders(<HarnessIndexPage type="rule" />, {
        initialEntries: ['/harness/rules?sort=newest'],
      });
      await screen.findByText('test_rule');
      const header = screen.getByRole('columnheader', { name: label });
      const button = within(header).getByRole('button');
      fireEvent.click(button);
      const first = label === 'Updated' ? descending : ascending;
      const second = label === 'Updated' ? ascending : descending;
      await waitFor(() =>
        expect(mockList).toHaveBeenLastCalledWith(
          'rule',
          expect.objectContaining({ sort: first, offset: 0 }),
        ),
      );
      await waitFor(() =>
        expect(header).toHaveAttribute(
          'aria-sort',
          first === ascending ? 'ascending' : 'descending',
        ),
      );
      fireEvent.click(button);
      await waitFor(() =>
        expect(mockList).toHaveBeenLastCalledWith(
          'rule',
          expect.objectContaining({ sort: second }),
        ),
      );
      await waitFor(() =>
        expect(header).toHaveAttribute(
          'aria-sort',
          second === ascending ? 'ascending' : 'descending',
        ),
      );
      expect(mockUpdateMetadata).not.toHaveBeenCalled();
      expect(mockMove).not.toHaveBeenCalled();
      expect(mockReorder).not.toHaveBeenCalled();
    },
  );

  it('restores canonical Order after Name directions and freezes every header throughout drag/save/recovery', async () => {
    const items = [makeItem(), makeItem({ id: 2, name: 'another_rule' })];
    mockList.mockResolvedValue({ items, total: 2 });
    let finish!: (value: unknown) => void;
    mockMove.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });
    await screen.findByText('test_rule');
    const name = screen.getByRole('button', { name: 'Name' });
    fireEvent.click(name);
    await waitFor(() =>
      expect(
        screen.getByRole('columnheader', { name: 'Name' }),
      ).toHaveAttribute('aria-sort', 'ascending'),
    );
    expect(
      screen.getByRole('button', { name: 'Reorder test_rule' }),
    ).toBeDisabled();
    fireEvent.click(name);
    await waitFor(() =>
      expect(
        screen.getByRole('columnheader', { name: 'Name' }),
      ).toHaveAttribute('aria-sort', 'descending'),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Order' }));
    await waitFor(() =>
      expect(
        screen.getByRole('columnheader', { name: 'Order' }),
      ).toHaveAttribute('aria-sort', 'ascending'),
    );
    await waitFor(() =>
      expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute(
        'data-disabled',
        'false',
      ),
    );
    act(() => {
      drag.start();
    });
    screen
      .getAllByRole('columnheader')
      .forEach((header) =>
        expect(within(header).getByRole('button')).toBeDisabled(),
      );
    let finished!: Promise<void>;
    act(() => {
      finished = drag.end({
        source: { index: 0 },
        destination: { index: 1 },
        draggableId: '1',
        reason: 'DROP',
      });
    });
    expect(mockMove).toHaveBeenCalledTimes(1);
    screen
      .getAllByRole('columnheader')
      .forEach((header) =>
        expect(within(header).getByRole('button')).toBeDisabled(),
      );
    await act(async () => {
      finish({});
      await finished;
    });
    screen
      .getAllByRole('columnheader')
      .forEach((header) =>
        expect(within(header).getByRole('button')).toBeEnabled(),
      );
  });

  it('removes accepted sort indicators while criteria change and ignores late ascending completion', async () => {
    let finishAsc!: (value: unknown) => void;
    let finishDesc!: (value: unknown) => void;
    const ascending = new Promise((resolve) => {
      finishAsc = resolve;
    });
    const descending = new Promise((resolve) => {
      finishDesc = resolve;
    });
    mockList.mockImplementation((_type, params) =>
      params.sort === 'name'
        ? ascending
        : params.sort === 'name_desc'
          ? descending
          : Promise.resolve({ items: [makeItem()], total: 25 }),
    );
    renderWithProviders(<HarnessIndexPage type="rule" />, {
      initialEntries: ['/harness/rules'],
    });
    await screen.findByText('test_rule');
    const name = screen.getByRole('button', { name: 'Name' });
    name.focus();
    fireEvent.click(name);
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    expect(document.querySelector('[aria-sort]')).toBeNull();
    expect(name).toHaveFocus();
    fireEvent.click(name);
    await act(async () => {
      finishDesc({
        items: [makeItem({ name: 'Accepted descending' })],
        total: 40,
      });
    });
    await screen.findByText('Accepted descending');
    await act(async () => {
      finishAsc({ items: [makeItem({ name: 'Stale ascending' })], total: 99 });
    });
    expect(screen.queryByText('Stale ascending')).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Name' })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
    expect(screen.getByText('Showing 1–10 of 40')).toBeInTheDocument();
    expect(mockMove).not.toHaveBeenCalled();
    expect(mockUpdateMetadata).not.toHaveBeenCalled();
  });
});
