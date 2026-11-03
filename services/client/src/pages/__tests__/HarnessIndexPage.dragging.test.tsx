import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { HarnessIndexPage } from '../HarnessIndexPage';

const drag = vi.hoisted(() => ({ start: undefined as undefined | (() => void), end: vi.fn() }));
vi.mock('@hello-pangea/dnd', () => ({
  DragDropContext: ({ children, onBeforeDragStart, onDragEnd }: any) => {
    drag.start = onBeforeDragStart;
    drag.end = onDragEnd;
    return <>{children}</>;
  },
  Droppable: ({ children, isDropDisabled }: any) => <div data-testid="harness-drop-zone" data-disabled={String(isDropDisabled)}>
    {children({ innerRef: () => {}, droppableProps: {}, placeholder: null })}
  </div>,
  Draggable: ({ children, draggableId, isDragDisabled }: any) => children({
    innerRef: () => {}, draggableProps: { style: {} },
    dragHandleProps: isDragDisabled ? null : {
      'data-rfd-drag-handle-draggable-id': draggableId, tabIndex: 0, role: 'button',
    },
  }, { isDragging: false }),
}));

const api = vi.hoisted(() => ({ list: vi.fn(), move: vi.fn(), reorder: vi.fn(), updateMetadata: vi.fn() }));
vi.mock('../../api', () => ({ api: { harness: { items: api } } }));

function item(id: number) {
  return {
    id, name: `visible_rule_${id}`, project: 'docs', agents: ['claude'], content: { body: 'Synthetic rule' },
    sort_key: id * 10, enabled: true, clone_as_skill: false, version: 2, configs: [],
    created_at: '2026-11-01T00:00:00.000000+00:00',
    updated_at: `2026-11-01T00:00:00.123${id}+00:00`,
  };
}

const rows = [item(101), item(104), item(107)];

function drop(source = 0, destination = 2) {
  return {
    draggableId: String(rows[source].id), reason: 'DROP', type: 'DEFAULT', mode: 'FLUID',
    source: { droppableId: 'harness-table', index: source },
    destination: { droppableId: 'harness-table', index: destination }, combine: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  drag.start = undefined;
  api.list.mockResolvedValue({ items: rows, total: 25 });
  api.move.mockResolvedValue(rows[0]);
  api.updateMetadata.mockResolvedValue({});
});

afterEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.useRealTimers();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe('Harness visible-anchor dragging', () => {
  it('moves a filtered second-page row after its last visible neighbor with exact timestamp tokens', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<HarnessIndexPage type="rule" />, { initialEntries: ['/harness/rules'] });
    await screen.findByText(rows[0].name);
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), { target: { value: 'visible' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Project scope' }), { target: { value: 'docs' } });
    await act(async () => { vi.advanceTimersByTime(350); });
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith('rule', expect.objectContaining({ name: 'visible', project: 'docs', offset: 0 })));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith('rule', expect.objectContaining({ offset: 10 })));
    await waitFor(() => expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute('data-disabled', 'false'));
    act(() => { drag.start?.(); });
    await act(async () => { await drag.end(drop()); });
    expect(api.move).toHaveBeenCalledTimes(1);
    expect(api.move).toHaveBeenCalledWith('rule', 101, {
      after_id: 107,
      expected_updated_at: rows[0].updated_at,
      expected_anchor_updated_at: rows[2].updated_at,
    });
    expect(api.reorder).not.toHaveBeenCalled();
    expect(api.list).toHaveBeenLastCalledWith('rule', expect.objectContaining({ offset: 10, name: 'visible', project: 'docs' }));
  });

  it('blocks a drag while raw search has not reached the applied criteria', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<HarnessIndexPage type="rule" />, { initialEntries: ['/harness/rules'] });
    await screen.findByText(rows[0].name);
    const previousDrop = drag.end;
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), { target: { value: 'unapplied' } });
    act(() => { drag.start?.(); });
    await act(async () => { await previousDrop(drop()); });
    expect(api.move).not.toHaveBeenCalled();
    expect(api.reorder).not.toHaveBeenCalled();
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute('data-disabled', 'true');
  });

  it('keeps native handles and SDK identity mounted through save and canonical reread', async () => {
    const move = deferred<ReturnType<typeof item>>();
    const reread = deferred<{ items: ReturnType<typeof item>[]; total: number }>();
    api.move.mockReturnValueOnce(move.promise);
    renderWithProviders(<HarnessIndexPage type="rule" />, { initialEntries: ['/harness/rules'] });
    await screen.findByText(rows[0].name);
    const handle = screen.getByRole('button', { name: `Reorder ${rows[0].name}` });
    handle.focus();
    api.list.mockReturnValueOnce(reread.promise);
    act(() => { drag.start?.(); });
    let finished!: Promise<void>;
    act(() => { finished = drag.end(drop()); });
    expect(api.move).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: `Reorder ${rows[0].name}` })).toBe(handle);
    expect(handle).toBeDisabled();
    expect(handle).toHaveAttribute('data-rfd-drag-handle-draggable-id', '101');
    for (const label of ['Search', 'Project scope']) expect(screen.getByRole('textbox', { name: label })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Sort' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    screen.getAllByRole('checkbox').forEach(toggle => expect(toggle).toBeDisabled());
    await act(async () => { await drag.end(drop()); });
    expect(api.move).toHaveBeenCalledTimes(1);
    await act(async () => { move.resolve(rows[0]); });
    expect(handle).toBeDisabled();
    expect(screen.getByText(rows[0].name)).toBeVisible();
    const canonical = [rows[1], rows[2], { ...rows[0], sort_key: 1_000, updated_at: '2026-11-01T00:00:01.654321+00:00' }];
    await act(async () => { reread.resolve({ items: canonical, total: 25 }); await finished; });
    expect(screen.getByRole('button', { name: `Reorder ${rows[0].name}` })).toBe(handle);
    expect(handle).toBeEnabled();
    expect(within(screen.getByTestId('harness-drop-zone')).getAllByText(/visible_rule_/).filter(node => node.tagName === 'DIV').map(node => node.textContent)).toEqual(canonical.map(row => row.name));
    expect(api.reorder).not.toHaveBeenCalled();
  });

  it('rolls back a rejected move and blocks further writes after the recovery read fails', async () => {
    api.move.mockRejectedValueOnce(new Error('private service diagnostic'));
    renderWithProviders(<HarnessIndexPage type="rule" />, { initialEntries: ['/harness/rules'] });
    await screen.findByText(rows[0].name);
    api.list.mockRejectedValueOnce(new Error('private read diagnostic'));
    act(() => { drag.start?.(); });
    await act(async () => { await drag.end(drop()); });
    expect(api.move).toHaveBeenCalledTimes(1);
    rows.forEach(row => expect(screen.getByText(row.name)).toBeVisible());
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute('data-disabled', 'true');
    expect(screen.getByRole('button', { name: `Reorder ${rows[0].name}` })).toBeDisabled();
    expect(screen.queryByText(/private .* diagnostic/)).not.toBeInTheDocument();
    await act(async () => { await drag.end(drop()); });
    expect(api.move).toHaveBeenCalledTimes(1);
    expect(api.reorder).not.toHaveBeenCalled();
    api.list.mockResolvedValueOnce({ items: rows, total: 25 });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute('data-disabled', 'false'));
  });

  it('ignores a captured drop after navigating to another Harness kind', async () => {
    const view = renderWithProviders(<HarnessIndexPage type="rule" />, { initialEntries: ['/harness/rules'] });
    await screen.findByText(rows[0].name);
    act(() => { drag.start?.(); });
    const previousDrop = drag.end;
    view.rerender(<HarnessIndexPage type="skill" />);
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith('skill', expect.anything()));
    await act(async () => { await previousDrop(drop()); });
    expect(api.move).not.toHaveBeenCalled();
    expect(api.reorder).not.toHaveBeenCalled();
    act(() => { drag.start?.(); });
    await act(async () => { await previousDrop(drop()); });
    expect(api.move).not.toHaveBeenCalled();
    await act(async () => { await drag.end(drop()); });
    expect(api.move).toHaveBeenCalledWith('skill', 101, expect.objectContaining({ after_id: 107 }));
  });

  it('anchors an upward move before the first visible neighbor', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />, { initialEntries: ['/harness/rules'] });
    await screen.findByText(rows[0].name);
    act(() => { drag.start?.(); });
    await act(async () => { await drag.end(drop(2, 0)); });
    expect(api.move).toHaveBeenCalledWith('rule', 107, {
      before_id: 101, expected_updated_at: rows[2].updated_at, expected_anchor_updated_at: rows[0].updated_at,
    });
  });

  it.each([
    { reason: 'CANCEL' }, { destination: null }, { draggableId: '999' },
    { destination: { index: -1 } }, { destination: { index: 3 } }, { source: { index: -1 } },
    { source: { index: 0.5 } }, { destination: { index: 0 } },
  ])('ignores invalid or canceled drop %j and releases its frozen controls', async override => {
    renderWithProviders(<HarnessIndexPage type="rule" />, { initialEntries: ['/harness/rules'] });
    await screen.findByText(rows[0].name);
    act(() => { drag.start?.(); });
    expect(screen.getByRole('textbox', { name: 'Search' })).toBeDisabled();
    await act(async () => { await drag.end({ ...drop(), ...override }); });
    expect(api.move).not.toHaveBeenCalled();
    expect(api.reorder).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox', { name: 'Search' })).toBeEnabled();
  });

  it('blocks old-page callbacks until a matching page response arrives', async () => {
    const nextPage = deferred<{ items: ReturnType<typeof item>[]; total: number }>();
    renderWithProviders(<HarnessIndexPage type="rule" />, { initialEntries: ['/harness/rules'] });
    await screen.findByText(rows[0].name);
    const previousStart = drag.start;
    const previousDrop = drag.end;
    api.list.mockReturnValueOnce(nextPage.promise);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    act(() => { previousStart?.(); drag.start?.(); });
    await act(async () => { await previousDrop(drop()); });
    expect(api.move).not.toHaveBeenCalled();
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute('data-disabled', 'true');
    await act(async () => { nextPage.resolve({ items: rows, total: 25 }); });
    act(() => { drag.start?.(); });
    await act(async () => { await drag.end(drop()); });
    expect(api.move).toHaveBeenCalledTimes(1);
  });

  it('reconciles an uncertain write without retry and uses canonical tokens for the next human drag', async () => {
    api.move.mockRejectedValueOnce(new DOMException('Lost response', 'TimeoutError'));
    renderWithProviders(<HarnessIndexPage type="rule" />, { initialEntries: ['/harness/rules'] });
    await screen.findByText(rows[0].name);
    const canonical = [rows[1], rows[2], { ...rows[0], updated_at: '2026-11-01T00:00:01.654321+00:00', sort_key: 50 }];
    api.list.mockResolvedValue({ items: canonical, total: 25 });
    act(() => { drag.start?.(); });
    await act(async () => { await drag.end(drop()); });
    expect(api.move).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: `Reorder ${rows[0].name}` })).toBeEnabled();
    act(() => { drag.start?.(); });
    await act(async () => { await drag.end({ ...drop(2, 0), draggableId: '101' }); });
    expect(api.move).toHaveBeenLastCalledWith('rule', 101, {
      before_id: 104, expected_updated_at: canonical[2].updated_at, expected_anchor_updated_at: canonical[0].updated_at,
    });
    expect(api.move).toHaveBeenCalledTimes(2);
  });

  it('keeps rollback rows when the write succeeds but its canonical read fails', async () => {
    renderWithProviders(<HarnessIndexPage type="rule" />, { initialEntries: ['/harness/rules'] });
    await screen.findByText(rows[0].name);
    api.list.mockRejectedValueOnce(new Error('Unavailable'));
    act(() => { drag.start?.(); });
    await act(async () => { await drag.end(drop()); });
    const names = within(screen.getByTestId('harness-drop-zone')).getAllByText(/visible_rule_/).filter(node => node.tagName === 'DIV');
    expect(names.map(node => node.textContent)).toEqual(rows.map(row => row.name));
    expect(screen.getByTestId('harness-drop-zone')).toHaveAttribute('data-disabled', 'true');
    expect(api.move).toHaveBeenCalledTimes(1);
  });

  it('never rereads or mutates another view after unmounting with an in-flight move', async () => {
    const move = deferred<ReturnType<typeof item>>();
    api.move.mockReturnValueOnce(move.promise);
    const view = renderWithProviders(<HarnessIndexPage type="rule" />, { initialEntries: ['/harness/rules'] });
    await screen.findByText(rows[0].name);
    act(() => { drag.start?.(); });
    let finished!: Promise<void>;
    act(() => { finished = drag.end(drop()); });
    view.unmount();
    await act(async () => { move.resolve(rows[0]); await finished; });
    expect(api.list).toHaveBeenCalledTimes(1);
    expect(api.move).toHaveBeenCalledTimes(1);
    expect(api.updateMetadata).not.toHaveBeenCalled();
  });
});
