import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { DropResult } from '@hello-pangea/dnd';
import type { ActionItemRow, Paginated } from '../../api';
import { Route, Routes } from 'react-router';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test-utils';
import { POLL_INTERVAL_MS } from '../../constants';
import { ActionItemsIndexPage } from '../ActionItemsIndexPage';
import { actionItem, deferred } from './actionItemFixture';

const drag = vi.hoisted(() => ({
  start: null as (() => void) | null,
  end: null as ((result: DropResult) => Promise<void>) | null,
}));
vi.mock('@hello-pangea/dnd', () => ({
  DragDropContext: ({ children, onBeforeCapture, onDragStart, onDragEnd }: { children: ReactNode; onBeforeCapture: () => void; onDragStart: () => void; onDragEnd: (result: DropResult) => Promise<void> }) => {
    drag.start = () => { onBeforeCapture(); onDragStart(); }; drag.end = onDragEnd; return <>{children}</>;
  },
  Droppable: ({ children, isDropDisabled }: { children: (provided: object) => ReactNode; isDropDisabled: boolean }) => children({
    innerRef: () => undefined, droppableProps: { 'data-testid': 'action-items-drop-zone', 'data-disabled': String(isDropDisabled) }, placeholder: null,
  }),
  Draggable: ({ children, disableInteractiveElementBlocking }: { children: (provided: object, snapshot: object) => ReactNode; disableInteractiveElementBlocking: boolean }) => children({
    innerRef: () => undefined, draggableProps: { style: {}, 'data-interactive-drag': String(disableInteractiveElementBlocking) }, dragHandleProps: {},
  }, { isDragging: false }),
}));
vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { actionItems: {
  list: vi.fn(), get: vi.fn(), update: vi.fn(), move: vi.fn(),
} } }));
import { api, ApiError } from '../../api';

const rows = [actionItem(1), actionItem(2), actionItem(3)];
const drop = (source = 0, destination = 2, id = 1): DropResult => ({
  draggableId: String(id), type: 'DEFAULT', source: { droppableId: 'action-items', index: source },
  destination: { droppableId: 'action-items', index: destination }, reason: 'DROP', mode: 'FLUID', combine: null,
});
const titles = () => within(screen.getByRole('table')).getAllByRole('button').filter(button => button.hasAttribute('aria-expanded')).map(button => button.getAttribute('aria-label'));

beforeEach(() => {
  vi.resetAllMocks();
  vi.spyOn(window, 'confirm').mockReturnValue(true); drag.start = null; drag.end = null;
  vi.mocked(api.actionItems.list).mockResolvedValue({ items: rows, total: 3 });
  vi.mocked(api.actionItems.get).mockImplementation(async id => actionItem(id));
  vi.mocked(api.actionItems.update).mockResolvedValue(actionItem(1, { revision: 2, status: 'completed' }));
  vi.mocked(api.actionItems.move).mockResolvedValue(actionItem(1, { revision: 2 }));
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

async function renderReady() {
  const rendered = renderWithProviders(<ActionItemsIndexPage />);
  await screen.findByRole('button', { name: 'Task 1' });
  return rendered;
}

describe('ActionItemsIndexPage', () => {
  it('keeps title disclosures separate from right-side completion and Edit controls', async () => {
    const saving = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.update).mockReturnValueOnce(saving.promise);
    await renderReady();
    expect(screen.getByRole('link', { name: 'New action item' })).toHaveAttribute('href', '/action-items/new');
    expect(screen.getByRole('button', { name: 'Task 1' })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('link', { name: 'Task 1' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reorder Task 1' }).closest('tr')).toHaveAttribute('data-interactive-drag', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Complete Task 1' }));
    expect(api.actionItems.update).toHaveBeenCalledWith(1, { expected_revision: 1, status: 'completed' });
    expect(screen.getByRole('button', { name: 'Complete Task 2' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Complete Task 1' })).toHaveTextContent('Complete');
    await act(async () => { saving.resolve(actionItem(1, { revision: 2, status: 'completed' })); });
  });

  it('uses tab-specific sorts and reopens completed items through explicit state', async () => {
    await renderReady();
    vi.mocked(api.actionItems.list).mockResolvedValue({ items: [actionItem(1, { status: 'completed', revision: 4 })], total: 1 });
    fireEvent.click(screen.getByRole('tab', { name: 'Completed' }));
    await screen.findByRole('button', { name: 'Reopen Task 1' });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'completed', sort: 'completed' }));
    expect(screen.queryByRole('option', { name: 'Manual order' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reopen Task 1' }));
    await waitFor(() => expect(api.actionItems.update).toHaveBeenCalledWith(1, { expected_revision: 4, status: 'open' }));
    fireEvent.click(screen.getByRole('tab', { name: 'All' }));
    await waitFor(() => expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'all', sort: 'newest' })));
  });

  it('debounces typing once, keeps search focused, and resets paging before the new query', async () => {
    vi.useFakeTimers();
    vi.mocked(api.actionItems.list).mockResolvedValue({ items: rows, total: 25 });
    renderWithProviders(<ActionItemsIndexPage />);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole('button', { name: 'Task 1' })).toBeInTheDocument();
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
    await screen.findByRole('button', { name: 'Current result' });
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
    await screen.findByRole('button', { name: 'Complete Task 11' });
    fireEvent.click(screen.getByRole('button', { name: 'Complete Task 11' }));
    await screen.findByRole('button', { name: 'Task 1' });
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
    fireEvent.click(screen.getByRole('button', { name: 'Complete Task 1' }));
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
    fireEvent.click(screen.getByRole('button', { name: 'Complete Task 1' }));
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
    await screen.findByRole('button', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByRole('button', { name: 'Task 11' });
    expect(api.actionItems.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }));
    act(() => { drag.start!(); });
    let ended!: Promise<void>;
    act(() => { ended = drag.end!(drop(0, 9, 11)); });
    expect(api.actionItems.move).toHaveBeenCalledWith(11, { expected_revision: 1, after_id: 20 });
    expect(titles().at(-1)).toBe('Task 11');
    expect(screen.getByRole('button', { name: 'Task 11' }).closest('tr')).toHaveTextContent('20');
    expect(screen.getByRole('button', { name: 'Task 12' }).closest('tr')?.querySelector('.action-item-priority')).toHaveTextContent('11');
    expect(screen.getByLabelText('Search action items')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Complete Task 12' })).toBeDisabled();
    await act(async () => { saving.resolve(actionItem(11, { revision: 2 })); await ended; });
  });

  it('moves upward before the next visible neighbor instead of replacing the whole queue', async () => {
    await renderReady();
    act(() => { drag.start!(); });
    await act(async () => { await drag.end!(drop(2, 0, 3)); });
    expect(api.actionItems.move).toHaveBeenCalledWith(3, { expected_revision: 1, before_id: 1 });
  });

  it('shows actual queue priorities in filtered title order and completed rows', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    vi.mocked(api.actionItems.list).mockResolvedValue({ items: [actionItem(24), actionItem(13), actionItem(3)], total: 3 });
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: 'Work' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'title' } });
    await screen.findByRole('button', { name: 'Task 24' });
    expect(within(screen.getByRole('table')).getAllByRole('columnheader').map(header => header.textContent)).toEqual(['Priority', 'Title', 'Project / tags', 'Updated', 'Actions']);
    expect([...screen.getByRole('table').querySelectorAll('.action-item-priority')].map(cell => cell.textContent)).toEqual(['24', '13', '3']);
    expect(screen.queryByRole('button', { name: /Reorder/ })).not.toBeInTheDocument();
    vi.mocked(api.actionItems.list).mockResolvedValue({ items: [actionItem(24, { status: 'completed' })], total: 1 });
    fireEvent.click(screen.getByRole('tab', { name: 'Completed' }));
    await screen.findByRole('button', { name: 'Reopen Task 24' });
    expect(screen.getByLabelText('No open queue priority')).toHaveTextContent('—');
    const actions = screen.getByRole('button', { name: 'Reopen Task 24' }).closest('td')!;
    expect(within(actions).getAllByRole('button').map(button => button.textContent)).toEqual(['Reopen', 'Edit']);
  });

  it('lazily discloses descriptions with native keyboard buttons and one open row', async () => {
    const user = userEvent.setup();
    vi.mocked(api.actionItems.get).mockImplementation(async id => actionItem(id, { description: id === 1 ? '**Next steps**' : '' }));
    await renderReady();
    expect(api.actionItems.get).not.toHaveBeenCalled();
    const title = screen.getByRole('button', { name: 'Task 1' });
    title.focus();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('region', { name: 'Task 1' })).toHaveTextContent('Next steps');
    expect(api.actionItems.get).toHaveBeenCalledWith(1);
    expect(title).toHaveAttribute('aria-expanded', 'true');
    expect(title).toHaveAttribute('aria-controls', 'action-description-1');
    expect(screen.getByRole('region', { name: 'Task 1' }).closest('td')).toHaveAttribute('colspan', '5');
    await user.keyboard(' ');
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Task 2' }));
    expect(await screen.findByRole('region', { name: 'Task 2' })).toHaveTextContent('No description added.');
    fireEvent.click(title);
    await screen.findByRole('region', { name: 'Task 1' });
    expect(screen.queryByRole('region', { name: 'Task 2' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Complete Task 3' }));
    expect(title).toHaveAttribute('aria-expanded', 'true');
  });

  it('retries a failed description read and ignores late responses after collapse', async () => {
    vi.mocked(api.actionItems.get).mockRejectedValueOnce(new Error('Private failure'));
    await renderReady();
    fireEvent.click(screen.getByRole('button', { name: 'Task 1' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load this description.');
    expect(screen.queryByText('Private failure')).not.toBeInTheDocument();
    const loading = deferred<ReturnType<typeof actionItem>>();
    vi.mocked(api.actionItems.get).mockReturnValueOnce(loading.promise);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    fireEvent.click(screen.getByRole('button', { name: 'Task 1' }));
    await act(async () => { loading.resolve(actionItem(1, { description: 'Stale description' })); });
    expect(screen.queryByText('Stale description')).not.toBeInTheDocument();
  });

  it('closes descriptions before drag capture and when paging or filters change', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.actionItems.list).mockResolvedValue({ items: rows, total: 25 });
    await renderReady();
    fireEvent.click(screen.getByRole('button', { name: 'Task 1' }));
    await screen.findByRole('region', { name: 'Task 1' });
    act(() => drag.start!());
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    await act(async () => drag.end!({ ...drop(), destination: null }));
    fireEvent.click(screen.getByRole('button', { name: 'Task 1' }));
    await screen.findByRole('region', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(screen.queryByRole('region')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Task 1' }));
    await screen.findByRole('region', { name: 'Task 1' });
    fireEvent.change(screen.getByLabelText('Search action items'), { target: { value: 'new' } });
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });

  it('opens Edit directly without reading a description or toggling its disclosure', async () => {
    renderWithProviders(<Routes><Route path="/" element={<ActionItemsIndexPage />} />
      <Route path="/action-items/:id" element={<p>Direct editor</p>} /></Routes>);
    await screen.findByRole('button', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit Task 1' }));
    expect(await screen.findByText('Direct editor')).toBeVisible();
    expect(api.actionItems.get).not.toHaveBeenCalled();
  });

  it('rejects a drag when only the queue positions changed during an in-flight poll', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderReady();
    const polling = deferred<Paginated<ActionItemRow>>();
    vi.mocked(api.actionItems.list).mockReturnValueOnce(polling.promise);
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    act(() => drag.start!());
    await act(async () => { polling.resolve({ items: rows.map(item => ({ ...item, priority: item.priority! + 1 })), total: 4 }); });
    await act(async () => drag.end!(drop()));
    expect(api.actionItems.move).not.toHaveBeenCalled();
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
    expect(screen.getByRole('button', { name: 'Complete Task 1' })).toBeEnabled();
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
    await screen.findByRole('button', { name: 'Task 1' });
  });
});
