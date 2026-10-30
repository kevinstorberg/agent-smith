import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { MeetingVocabulary } from '../MeetingVocabulary';

vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { meetings: { vocabulary: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() } } } };
});
import { api, ApiError } from '../../api';

const term = { id: 'term-1', term: 'LTV', definition: 'Lifetime value', revision: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' };
const vocabulary = api.meetings.vocabulary;

function open() {
  renderWithProviders(<MeetingVocabulary />);
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(vocabulary.list).mockResolvedValue({ items: [term], total: 1 });
  vi.mocked(vocabulary.get).mockResolvedValue({ ...term, revision: 2, definition: 'Changed elsewhere' });
  vi.mocked(vocabulary.create).mockResolvedValue(term);
  vi.mocked(vocabulary.update).mockResolvedValue({ ...term, revision: 2 });
  vi.mocked(vocabulary.remove).mockResolvedValue({ id: term.id, deleted: true });
});
afterEach(() => vi.useRealTimers());

describe('MeetingVocabulary', () => {
  it('shows the vocabulary directly with its primary add action', async () => {
    renderWithProviders(<MeetingVocabulary />);
    expect(screen.getByRole('region', { name: 'Meeting vocabulary' }).querySelector('details')).toBeNull();
    expect(screen.getByRole('heading', { name: 'Vocabulary' })).toBeVisible();
    expect(await screen.findByText('Lifetime value')).toBeInTheDocument();
    expect(screen.getByText('Terms and meanings that guide new meeting memories.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add term' })).toHaveClass('btn-primary');
  });

  it('creates a normalized term and refreshes the saved list', async () => {
    vi.mocked(vocabulary.list).mockResolvedValueOnce({ items: [], total: 0 });
    open();
    await screen.findByText('No vocabulary terms yet.');
    fireEvent.click(screen.getByRole('button', { name: 'Add term' }));
    fireEvent.change(screen.getByLabelText('Term'), { target: { value: ' LTV ' } });
    fireEvent.change(screen.getByLabelText('Meaning / definition (optional)'), { target: { value: ' Lifetime value ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save term' }));
    await waitFor(() => expect(vocabulary.create).toHaveBeenCalledWith({ term: 'LTV', definition: 'Lifetime value' }));
    expect(await screen.findByText('Lifetime value')).toBeInTheDocument();
    expect(screen.queryByRole('form', { name: 'Vocabulary term' })).not.toBeInTheDocument();
  });

  it('edits with the captured revision and cancels without a write', async () => {
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit LTV' }));
    expect(screen.getByLabelText('Term')).toHaveValue('LTV');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(vocabulary.update).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Edit LTV' }));
    fireEvent.change(screen.getByLabelText('Meaning / definition (optional)'), { target: { value: 'Long-term value' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save term' }));
    await waitFor(() => expect(vocabulary.update).toHaveBeenCalledWith(term.id, { expected_revision: 1, term: 'LTV', definition: 'Long-term value' }));
  });

  it('retains an edit after409 and requires an explicit retry using the refreshed revision', async () => {
    vi.mocked(vocabulary.list).mockResolvedValueOnce({ items: [term], total: 1 });
    vi.mocked(vocabulary.list).mockResolvedValue({ items: [{ ...term, revision: 2, definition: 'Changed elsewhere' }], total: 1 });
    vi.mocked(vocabulary.update).mockRejectedValueOnce(new ApiError('private conflict detail', 409));
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit LTV' }));
    fireEvent.change(screen.getByLabelText('Meaning / definition (optional)'), { target: { value: 'My definition draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save term' }));
    expect(await screen.findByText('This term changed. Review the latest entry, then save again.')).toBeInTheDocument();
    expect(await screen.findByText('Latest saved: LTV — Changed elsewhere')).toBeInTheDocument();
    expect(screen.getByLabelText('Meaning / definition (optional)')).toHaveValue('My definition draft');
    expect(vocabulary.update).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('private conflict detail')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save term' }));
    await waitFor(() => expect(vocabulary.update).toHaveBeenLastCalledWith(term.id, { expected_revision: 2, term: 'LTV', definition: 'My definition draft' }));
  });

  it('requires confirmation to delete and preserves the current revision', async () => {
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Delete LTV' }));
    expect(vocabulary.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel delete' }));
    expect(vocabulary.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete LTV' }));
    vi.mocked(vocabulary.list).mockResolvedValue({ items: [], total: 0 });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() => expect(vocabulary.remove).toHaveBeenCalledWith(term.id, 1));
    expect(await screen.findByText('No vocabulary terms yet.')).toBeInTheDocument();
  });

  it('asks for new confirmation after a delete conflict instead of deleting the changed entry', async () => {
    vi.mocked(vocabulary.remove).mockRejectedValueOnce(new ApiError('private conflict detail', 409));
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Delete LTV' }));
    vi.mocked(vocabulary.list).mockResolvedValue({ items: [{ ...term, revision: 2, definition: 'Changed elsewhere' }], total: 1 });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    expect(await screen.findByText('This term changed. Review it before deleting.')).toBeInTheDocument();
    expect(await screen.findByText('Changed elsewhere')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm delete' })).not.toBeInTheDocument();
    expect(vocabulary.remove).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Delete LTV' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() => expect(vocabulary.remove).toHaveBeenLastCalledWith(term.id, 2));
  });

  it('shows a retryable list failure and validates a nonblank term', async () => {
    vi.mocked(vocabulary.list).mockRejectedValueOnce(new Error('private backend error'));
    open();
    expect(await screen.findByText('Could not load vocabulary.')).toBeInTheDocument();
    expect(screen.queryByText('No vocabulary terms yet.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Lifetime value')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Add term' }));
    fireEvent.change(screen.getByLabelText('Term'), { target: { value: '  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save term' }));
    expect(screen.getByText('A term is required.')).toBeInTheDocument();
    expect(vocabulary.create).not.toHaveBeenCalled();
    expect(screen.queryByText('private backend error')).not.toBeInTheDocument();
  });

  it('uses one compact table row with adjacent edit and delete controls', async () => {
    open();
    const table = await screen.findByRole('table', { name: 'Vocabulary terms' });
    const row = within(table).getAllByRole('row')[1];
    const buttons = within(row).getAllByRole('button');
    expect(buttons.map(button => button.textContent)).toEqual(['Edit', 'Delete']);
    expect(buttons[0].parentElement).toBe(buttons[1].parentElement);
    expect(buttons[0].parentElement).toHaveClass('vocabulary-actions');
    expect(vocabulary.list).toHaveBeenCalledWith({ limit: 10, offset: 0, q: '' });
  });

  it('debounces typing while retaining search focus and ignores stale results', async () => {
    open();
    await screen.findByText('Lifetime value');
    vi.useFakeTimers();
    const input = screen.getByLabelText('Search vocabulary');
    input.focus();
    let finish!: (value: { items: typeof term[]; total: number }) => void;
    vi.mocked(vocabulary.list).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    fireEvent.change(input, { target: { value: 'old' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(299); });
    expect(vocabulary.list).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(vocabulary.list).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: 'old' });
    vi.mocked(vocabulary.list).mockResolvedValue({ items: [{ ...term, definition: 'Newest response' }], total: 1 });
    fireEvent.change(input, { target: { value: 'new' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    await act(async () => { finish({ items: [{ ...term, definition: 'Stale response' }], total: 1 }); });
    expect(screen.getByText('Newest response')).toBeVisible();
    expect(screen.queryByText('Stale response')).not.toBeInTheDocument();
    expect(input).toHaveFocus();
  });

  it('resets the page for a new search and keeps an off-page edit draft', async () => {
    vi.mocked(vocabulary.list).mockResolvedValue({ items: [term], total: 11 });
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
    await waitFor(() => expect(vocabulary.list).toHaveBeenLastCalledWith({ limit: 10, offset: 10, q: '' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Edit LTV' }));
    fireEvent.change(screen.getByLabelText('Meaning / definition (optional)'), { target: { value: 'My preserved draft' } });
    fireEvent.change(screen.getByLabelText('Search vocabulary'), { target: { value: 'unmatched' } });
    vi.mocked(vocabulary.list).mockResolvedValue({ items: [], total: 0 });
    await waitFor(() => expect(vocabulary.list).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: 'unmatched' }));
    expect(screen.getByLabelText('Meaning / definition (optional)')).toHaveValue('My preserved draft');
    expect(vocabulary.list).not.toHaveBeenCalledWith({ limit: 10, offset: 10, q: 'unmatched' });
  });

  it('clamps to the previous valid page after deleting the last item', async () => {
    vi.mocked(vocabulary.list).mockResolvedValue({ items: [term], total: 11 });
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
    await waitFor(() => expect(vocabulary.list).toHaveBeenLastCalledWith({ limit: 10, offset: 10, q: '' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete LTV' }));
    vi.mocked(vocabulary.list).mockResolvedValueOnce({ items: [], total: 10 }).mockResolvedValue({ items: [term], total: 10 });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() => expect(vocabulary.list).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: '' }));
    expect(await screen.findByText('Lifetime value')).toBeVisible();
  });

  it('rereads a conflicted entry by ID even when it is outside the current search page', async () => {
    vi.mocked(vocabulary.update).mockRejectedValueOnce(new ApiError('Conflict', 409));
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit LTV' }));
    fireEvent.change(screen.getByLabelText('Meaning / definition (optional)'), { target: { value: 'My off-page draft' } });
    vi.mocked(vocabulary.list).mockResolvedValue({ items: [], total: 0 });
    fireEvent.change(screen.getByLabelText('Search vocabulary'), { target: { value: 'absent' } });
    await screen.findByText('No vocabulary terms match your search.');
    fireEvent.click(screen.getByRole('button', { name: 'Save term' }));
    expect(await screen.findByText('Latest saved: LTV — Changed elsewhere')).toBeVisible();
    expect(vocabulary.get).toHaveBeenCalledWith(term.id);
    expect(screen.getByLabelText('Meaning / definition (optional)')).toHaveValue('My off-page draft');
    fireEvent.click(screen.getByRole('button', { name: 'Save term' }));
    await waitFor(() => expect(vocabulary.update).toHaveBeenLastCalledWith(term.id, { term: 'LTV', definition: 'My off-page draft', expected_revision: 2 }));
  });

  it('keeps Save blocked after a failed conflict read and permits an explicit refresh', async () => {
    vi.mocked(vocabulary.update).mockRejectedValueOnce(new ApiError('Conflict', 409));
    vi.mocked(vocabulary.get).mockRejectedValueOnce(new Error('private failure'));
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit LTV' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save term' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Retry term refresh' }));
    expect(screen.getByRole('button', { name: 'Save term' })).toBeDisabled();
    expect(await screen.findByText('Latest saved: LTV — Changed elsewhere')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Save term' })).toBeEnabled();
    expect(screen.getByLabelText('Term')).toHaveValue('LTV');
    expect(screen.queryByText('private failure')).not.toBeInTheDocument();
  });

  it('refreshes the live search and page after a save started on a different page', async () => {
    vi.mocked(vocabulary.list).mockResolvedValue({ items: [term], total: 11 });
    let finish!: (value: typeof term) => void;
    vi.mocked(vocabulary.update).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
    await waitFor(() => expect(vocabulary.list).toHaveBeenLastCalledWith({ limit: 10, offset: 10, q: '' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Edit LTV' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save term' }));
    vi.mocked(vocabulary.list).mockResolvedValue({ items: [term], total: 1 });
    fireEvent.change(screen.getByLabelText('Search vocabulary'), { target: { value: 'LTV' } });
    await waitFor(() => expect(vocabulary.list).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: 'LTV' }));
    await act(async () => { finish(term); });
    expect(vocabulary.list).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: 'LTV' });
    expect(vocabulary.list).not.toHaveBeenCalledWith({ limit: 10, offset: 10, q: 'LTV' });
  });

  it('retains a removed conflict draft and clears a pending delete when search changes', async () => {
    vi.mocked(vocabulary.update).mockRejectedValueOnce(new ApiError('Conflict', 409));
    vi.mocked(vocabulary.get).mockRejectedValueOnce(new ApiError('Not found', 404));
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit LTV' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save term' }));
    expect(await screen.findByText('This term was removed. Cancel to add a new entry.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Save term' })).toBeDisabled();
    expect(screen.getByLabelText('Term')).toHaveValue('LTV');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete LTV' }));
    fireEvent.change(screen.getByLabelText('Search vocabulary'), { target: { value: 'LTV' } });
    expect(screen.queryByRole('button', { name: 'Confirm delete' })).not.toBeInTheDocument();
    expect(vocabulary.remove).not.toHaveBeenCalled();
  });
});
