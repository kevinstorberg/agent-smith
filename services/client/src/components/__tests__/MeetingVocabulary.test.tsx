import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { MeetingVocabulary } from '../MeetingVocabulary';

vi.mock('../../api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, api: { meetings: { vocabulary: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() } } } };
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
  vi.mocked(vocabulary.create).mockResolvedValue(term);
  vi.mocked(vocabulary.update).mockResolvedValue({ ...term, revision: 2 });
  vi.mocked(vocabulary.remove).mockResolvedValue({ id: term.id, deleted: true });
});

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
});
