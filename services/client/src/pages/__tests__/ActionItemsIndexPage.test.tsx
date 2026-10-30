import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { DropResult } from '@hello-pangea/dnd';
import type { ActionItemRow, Paginated } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { POLL_INTERVAL_MS } from '../../constants';
import { ActionItemsIndexPage } from '../ActionItemsIndexPage';
import { actionItem, deferred } from './actionItemFixture';

const drag = vi.hoisted(() => ({
  start: null as (() => void) | null,
  end: null as ((result: DropResult) => Promise<void>) | null,
}));
vi.mock('@hello-pangea/dnd', () => ({
  DragDropContext: ({ children, onDragStart, onDragEnd }: { children: ReactNode; onDragStart: () => void; onDragEnd: (result: DropResult) => Promise<void> }) => {
    drag.start = onDragStart; drag.end = onDragEnd; return <>{children}</>;
  },
  Droppable: ({ children, isDropDisabled }: { children: (provided: object) => ReactNode; isDropDisabled: boolean }) => children({
    innerRef: () => undefined, droppableProps: { 'data-testid': 'action-items-drop-zone', 'data-disabled': String(isDropDisabled) }, placeholder: null,
  }),
  Draggable: ({ children, disableInteractiveElementBlocking }: { children: (provided: object, snapshot: object) => ReactNode; disableInteractiveElementBlocking: boolean }) => children({
    innerRef: () => undefined, draggableProps: { style: {}, 'data-interactive-drag': String(disableInteractiveElementBlocking) }, dragHandleProps: {},
  }, { isDragging: false }),
}));
vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { actionItems: {
  list: vi.fn(), update: vi.fn(), move: vi.fn(),
} } }));
import { api, ApiError } from '../../api';

const rows = [actionItem(1), actionItem(2), actionItem(3)];
const drop = (source = 0, destination = 2, id = 1): DropResult => ({
  draggableId: String(id), type: 'DEFAULT', source: { droppableId: 'action-items', index: source },
  destination: { droppableId: 'action-items', index: destination }, reason: 'DROP', mode: 'FLUID', combine: null,
});
const titles = () => within(screen.getByRole('table')).getAllByRole('link').map(link => link.textContent);

beforeEach(() => {
  vi.resetAllMocks(); drag.start = null; drag.end = null;
  vi.mocked(api.actionItems.list).mockResolvedValue({ items: rows, total: 3 });
  vi.mocked(api.actionItems.update).mockResolvedValue(actionItem(1, { revision: 2, status: 'completed' }));
  vi.mocked(api.actionItems.move).mockResolvedValue(actionItem(1, { revision: 2 }));
});
afterEach(() => vi.useRealTimers());

async function renderReady() {
  const rendered = renderWithProviders(<ActionItemsIndexPage />);
  await screen.findByRole('link', { name: 'Task 1' });
  return rendered;
}

describe('ActionItemsIndexPage', () => {
  it('keeps title navigation separate from accessible desired-state completion controls', async () => {
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.update).mockReturnValueOnce(saving.promise);
    await renderReady();
    expect(screen.getByRole('link', { name: 'New action item' })).toHaveAttribute('href', '/action-items/new');
    expect(screen.getByRole('link', { name: 'Task 1' })).toHaveAttribute('href', '/action-items/1');
    expect(screen.getByRole('button', { name: 'Reorder Task 1' }).closest('tr')).toHaveAttribute('data-interactive-drag', 'true');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Complete Task 1' }));
    expect(api.actionItems.update).toHaveBeenCalledWith(1, { expected_revision: 1, status: 'completed' });
    expect(screen.getByRole('checkbox', { name: 'Complete Task 2' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Complete Task 1' })).not.toBeChecked();
    await act(async () => { saving.resolve(actionItem(1, { revision: 2, status: 'completed' })); });
  });

  it('uses tab-specific sorts and reopens completed items through explicit state', async () => {
    await renderReady();
    vi.mocked(api.actionItems.list).mockResolvedValue({ items: [actionItem(1, { status: 'completed', revision: 4 })], total: 1 });
    fireEvent.click(screen.getByRole('tab', { name: 'Completed' }));
    await screen.findByRole('checkbox', { name: 'Reopen Task 1' });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'completed', sort: 'completed' }));
    expect(screen.queryByRole('option', { name: 'Manual order' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Reopen Task 1' }));
    await waitFor(() => expect(api.actionItems.update).toHaveBeenCalledWith(1, { expected_revision: 4, status: 'open' }));
    fireEvent.click(screen.getByRole('tab', { name: 'All' }));
    await waitFor(() => expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'all', sort: 'newest' })));
  });

  it('debounces typing once, keeps search focused, and resets paging before the new query', async () => {
    vi.useFakeTimers();
    vi.mocked(api.actionItems.list).mockResolvedValue({ items: rows, total: 25 });
    renderWithProviders(<ActionItemsIndexPage />);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole('link', { name: 'Task 1' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await act(async () => { await Promise.resolve(); });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }));
    vi.mocked(api.actionItems.list).mockClear();
    const search = screen.getByLabelText('Search action items');
    search.focus();
    fireEvent.change(search, { target: { value: 'Ro' } });
    await act(async () => { vi.advanceTimersByTime(200); });
    fireEvent.change(search, { target: { value: 'Roadmap' } });
    await act(async () => { vi.advanceTimersByTime(299); });
    expect(api.actionItems.list).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(api.actionItems.list).toHaveBeenCalledTimes(1);
    expect(api.actionItems.list).toHaveBeenCalledWith(expect.objectContaining({ q: 'Roadmap', offset: 0 }));
    expect(search).toHaveFocus();
    expect(screen.getByTestId('action-items-drop-zone')).toHaveAttribute('data-disabled', 'true');
  });

  it('sends combined project/tags filters to the server and applies select changes immediately', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: 'Paralign' } });
    fireEvent.change(screen.getByLabelText('Tags'), { target: { value: 'product, security' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ project: 'Paralign', tags: ['product', 'security'], offset: 0 }));
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'title' } });
    await waitFor(() => expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'title', project: 'Paralign', tags: ['product', 'security'] })));
  });

  it('ignores late search responses after newer criteria return', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    const stale = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list).mockReturnValueOnce(stale.promise).mockResolvedValueOnce({ items: [actionItem(4, { title: 'Current result' })], total: 1 });
    fireEvent.change(screen.getByLabelText('Search action items'), { target: { value: 'old' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    fireEvent.change(screen.getByLabelText('Search action items'), { target: { value: 'new' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    await screen.findByRole('link', { name: 'Current result' });
    await act(async () => { stale.resolve({ items: [actionItem(5, { title: 'Stale result' })], total: 1 }); });
    expect(screen.queryByText('Stale result')).not.toBeInTheDocument();
    expect(screen.getByText('Current result')).toBeVisible();
  });

  it('clamps an emptied last page after completion', async () => {
    vi.mocked(api.actionItems.list).mockResolvedValueOnce({ items: rows, total: 11 })
      .mockResolvedValueOnce({ items: [actionItem(11)], total: 11 })
      .mockResolvedValueOnce({ items: [], total: 10 })
      .mockResolvedValueOnce({ items: rows, total: 10 });
    await renderReady();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByRole('checkbox', { name: 'Complete Task 11' });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Complete Task 11' }));
    await screen.findByRole('link', { name: 'Task 1' });
    expect(api.actionItems.update).toHaveBeenCalledWith(11, { expected_revision: 1, status: 'completed' });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }));
  });

  it('refreshes the current filtered page after a pending status write rather than its captured old offset', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.update).mockReturnValueOnce(saving.promise);
    vi.mocked(api.actionItems.list).mockResolvedValue({ items: rows, total: 25 });
    await renderReady();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 })));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Complete Task 1' }));
    fireEvent.change(screen.getByLabelText('Search action items'), { target: { value: 'Current scope' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    await waitFor(() => expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0, q: 'Current scope' })));
    vi.mocked(api.actionItems.list).mockClear();
    await act(async () => { saving.resolve(actionItem(1, { status: 'completed' })); });
    expect(api.actionItems.list).toHaveBeenCalledTimes(1);
    expect(api.actionItems.list).toHaveBeenCalledWith(expect.objectContaining({ offset: 0, q: 'Current scope' }));
  });

  it('does not refetch after a pending write finishes on an unmounted page', async () => {
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.update).mockReturnValueOnce(saving.promise);
    const rendered = await renderReady();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Complete Task 1' }));
    rendered.unmount();
    vi.mocked(api.actionItems.list).mockClear();
    await act(async () => { saving.resolve(actionItem(1, { status: 'completed' })); });
    expect(api.actionItems.list).not.toHaveBeenCalled();
  });

  it('sends page-end relative intent after the last visible neighbor and freezes controls through its save', async () => {
    const page = Array.from({ length: 10 }, (_, index) => actionItem(index + 11));
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.move).mockReturnValueOnce(saving.promise);
    vi.mocked(api.actionItems.list).mockResolvedValueOnce({ items: rows, total: 25 }).mockResolvedValue({ items: page, total: 25 });
    renderWithProviders(<ActionItemsIndexPage />);
    await screen.findByRole('link', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByRole('link', { name: 'Task 11' });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }));
    act(() => { drag.start!(); });
    let ended!: Promise<void>;
    act(() => { ended = drag.end!(drop(0, 9, 11)); });
    expect(api.actionItems.move).toHaveBeenCalledWith(11, { expected_revision: 1, after_id: 20 });
    expect(titles().at(-1)).toBe('Task 11');
    expect(screen.getByLabelText('Search action items')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Complete Task 12' })).toBeDisabled();
    await act(async () => { saving.resolve(actionItem(11, { revision: 2 })); await ended; });
  });

  it('moves upward before the next visible neighbor instead of replacing the whole queue', async () => {
    await renderReady();
    act(() => { drag.start!(); });
    await act(async () => { await drag.end!(drop(2, 0, 3)); });
    expect(api.actionItems.move).toHaveBeenCalledWith(3, { expected_revision: 1, before_id: 1 });
  });

  it('rolls an optimistic reorder back and reloads persisted order after a conflict', async () => {
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.move).mockReturnValueOnce(saving.promise);
    await renderReady();
    act(() => { drag.start!(); });
    let ended!: Promise<void>;
    act(() => { ended = drag.end!(drop()); });
    expect(titles()).toEqual(['Task 2', 'Task 3', 'Task 1']);
    await act(async () => { saving.reject(new ApiError('Source changed', 409)); await ended; });
    expect(titles()).toEqual(['Task 1', 'Task 2', 'Task 3']);
    expect(screen.getByRole('checkbox', { name: 'Complete Task 1' })).toBeEnabled();
    expect(api.actionItems.list).toHaveBeenCalledTimes(2);
  });

  it('blocks captured drag callbacks after filtering and never sends a filtered reorder', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    const oldStart = drag.start!; const oldEnd = drag.end!;
    fireEvent.change(screen.getByLabelText('Search action items'), { target: { value: 'filtered' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    act(() => { oldStart(); });
    await act(async () => { await oldEnd(drop()); });
    expect(api.actionItems.move).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Reorder Task 1' })).not.toBeInTheDocument();
  });

  it('keeps displayed rows frozen and cancels a drag if an already-started read changes membership', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    const polling = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list).mockReturnValueOnce(polling.promise);
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    act(() => { drag.start!(); });
    await act(async () => { polling.resolve({ items: [rows[0], rows[2]], total: 2 }); });
    expect(titles()).toEqual(['Task 1', 'Task 2', 'Task 3']);
    await act(async () => { await drag.end!(drop()); });
    expect(api.actionItems.move).not.toHaveBeenCalled();
  });

  it('pauses polling during a drag and ignores canceled or unchanged drops', async () => {
    vi.useFakeTimers();
    renderWithProviders(<ActionItemsIndexPage />);
    await act(async () => { await Promise.resolve(); });
    await act(async () => { drag.start!(); });
    vi.mocked(api.actionItems.list).mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2); });
    expect(api.actionItems.list).not.toHaveBeenCalled();
    await act(async () => { await drag.end!({ ...drop(), destination: null, reason: 'CANCEL' }); });
    act(() => { drag.start!(); });
    await act(async () => { await drag.end!(drop(0, 0)); });
    expect(api.actionItems.move).not.toHaveBeenCalled();
  });

  it('keeps labeled filters available through loading and retryable read failures', async () => {
    vi.mocked(api.actionItems.list).mockRejectedValueOnce(new Error('Private diagnostic'));
    renderWithProviders(<ActionItemsIndexPage />);
    expect(screen.getByLabelText('Search action items')).toBeVisible();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load action items.');
    expect(screen.queryByText('Private diagnostic')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByRole('link', { name: 'Task 1' });
  });
});
