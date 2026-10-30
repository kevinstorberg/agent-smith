import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router';
import { renderWithProviders } from '../../test-utils';
import { POLL_INTERVAL_MS } from '../../constants';
import { ActionItemDetailPage } from '../ActionItemDetailPage';
import { actionItem, deferred } from './actionItemFixture';
import type { ActionItem } from '../../api';

const navigate = vi.fn();
const routing = vi.hoisted(() => ({ real: false }));
vi.mock('react-router', async original => {
  const actual = await original<typeof import('react-router')>();
  return { ...actual, useNavigate: () => {
    const realNavigate = actual.useNavigate();
    return routing.real ? realNavigate : navigate;
  } };
});
vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), api: { actionItems: {
  get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(),
} } }));
import { api, ApiError } from '../../api';

function renderPage(id: number | 'new' = 1) {
  return renderWithProviders(<Routes><Route path="/action-items/:id" element={<ActionItemDetailPage />} /></Routes>, { initialEntries: [`/action-items/${id}`] });
}

beforeEach(() => {
  vi.resetAllMocks();
  routing.real = false;
  vi.mocked(api.actionItems.get).mockResolvedValue(actionItem(1));
  vi.mocked(api.actionItems.create).mockResolvedValue(actionItem(2));
  vi.mocked(api.actionItems.update).mockResolvedValue(actionItem(1, { revision: 2 }));
  vi.mocked(api.actionItems.remove).mockResolvedValue({ deleted: true, id: 1 });
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('ActionItemDetailPage', () => {
  it('opens the saved resource in view mode after a real new-to-detail route transition', async () => {
    routing.real = true;
    vi.mocked(api.actionItems.create).mockResolvedValue(actionItem(2, { title: 'Created task' }));
    vi.mocked(api.actionItems.get).mockResolvedValue(actionItem(2, { title: 'Created task' }));
    renderWithProviders(<Routes>
      <Route path="/action-items/new" element={<ActionItemDetailPage />} />
      <Route path="/action-items/:id" element={<ActionItemDetailPage />} />
    </Routes>, { initialEntries: ['/action-items/new'] });
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Created task' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('heading', { name: 'Created task' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Edit' })).toBeEnabled();
    expect(screen.queryByLabelText('Title')).not.toBeInTheDocument();
  });

  it('creates from the standard Save/Cancel form with one request UUID and explicit optional values', async () => {
    renderPage('new');
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: '  Follow up  ' } });
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: ' Work ' } });
    fireEvent.change(screen.getByLabelText('Tags'), { target: { value: 'product, security' } });
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: '## Next steps' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.actionItems.create).toHaveBeenCalledWith({
      title: 'Follow up', description: '## Next steps', project: 'Work', tags: ['product', 'security'], request_id: expect.any(String),
    }));
    expect(vi.mocked(api.actionItems.create).mock.calls[0][0].request_id).toMatch(/^[\da-f-]{36}$/);
    expect(navigate).toHaveBeenCalledWith('/action-items/2', { replace: true });
    expect(api.actionItems.get).not.toHaveBeenCalled();
  });

  it('freezes an uncertain creation and retries its identical UUID and original payload', async () => {
    vi.mocked(api.actionItems.create).mockRejectedValueOnce(new Error('The save could not be confirmed.'));
    renderPage('new');
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Original task' } });
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Frozen details' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByRole('alert');
    const first = vi.mocked(api.actionItems.create).mock.calls[0][0];
    for (const field of ['Title', 'Description', 'Project', 'Tags']) expect(screen.getByLabelText(field)).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.actionItems.create).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.actionItems.create).mock.calls[1][0]).toEqual(first);
    expect(navigate).toHaveBeenCalledWith('/action-items/2', { replace: true });
  });

  it('does not navigate away from a newer page when a pending create finishes after unmount', async () => {
    const saving = deferred<ActionItem>();
    vi.mocked(api.actionItems.create).mockReturnValueOnce(saving.promise);
    const rendered = renderPage('new');
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Pending creation' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(api.actionItems.create).toHaveBeenCalledTimes(1);
    rendered.unmount();
    await act(async () => { saving.resolve(actionItem(2)); });
    expect(navigate).not.toHaveBeenCalled();
  });

  it('unlocks a proven invalid creation and uses a fresh UUID for the corrected draft', async () => {
    vi.mocked(api.actionItems.create).mockRejectedValueOnce(new ApiError('Tags are too long', 422));
    renderPage('new');
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Invalid draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByRole('alert');
    const first = vi.mocked(api.actionItems.create).mock.calls[0][0];
    expect(screen.getByLabelText('Title')).toBeEnabled();
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Corrected draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.actionItems.create).toHaveBeenCalledTimes(2));
    const corrected = vi.mocked(api.actionItems.create).mock.calls[1][0];
    expect(corrected.title).toBe('Corrected draft');
    expect(corrected.request_id).not.toBe(first.request_id);
  });

  it('unlocks after validation resolves a previously uncertain create replay', async () => {
    vi.mocked(api.actionItems.create).mockRejectedValueOnce(new Error('Network interrupted'))
      .mockRejectedValueOnce(new ApiError('Invalid original tags', 422));
    renderPage('new');
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Original' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByText('Network interrupted');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByText('Invalid original tags');
    expect(screen.getByLabelText('Title')).toBeEnabled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(vi.mocked(api.actionItems.create).mock.calls[1][0]).toEqual(vi.mocked(api.actionItems.create).mock.calls[0][0]);
  });

  it('does not submit a blank title and retains Cancel', async () => {
    renderPage('new');
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: '   ' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Save' })); });
    expect(api.actionItems.create).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(navigate).toHaveBeenCalledWith('/action-items');
  });

  it('edits using the captured revision and sends explicit clears', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Tags'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.actionItems.update).toHaveBeenCalledWith(1, { expected_revision: 1, title: 'Task 1', description: '', project: null, tags: [] }));
  });

  it('keeps the edit-start revision when an earlier polling read finishes during editing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const polling = deferred<ActionItem>();
    vi.mocked(api.actionItems.get).mockResolvedValueOnce(actionItem(1)).mockReturnValueOnce(polling.promise);
    renderPage();
    await screen.findByRole('heading', { name: 'Task 1' });
    await act(async () => { vi.advanceTimersByTime(POLL_INTERVAL_MS); });
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'My draft' } });
    await act(async () => { polling.resolve(actionItem(1, { title: 'New concurrent title', revision: 4 })); });
    expect(screen.getByLabelText('Title')).toHaveValue('My draft');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.actionItems.update).toHaveBeenCalledWith(1, expect.objectContaining({ expected_revision: 1, title: 'My draft' })));
  });

  it('retains conflict drafts, blocks failed-reread retries, and compares a successful current version before retry', async () => {
    vi.mocked(api.actionItems.update).mockRejectedValueOnce(new ApiError('Conflict', 409));
    vi.mocked(api.actionItems.get).mockResolvedValueOnce(actionItem(1)).mockRejectedValueOnce(new Error('Refresh unavailable'))
      .mockResolvedValueOnce(actionItem(1, { revision: 7, title: 'Current saved title', description: 'Current saved details' }));
    renderPage();
    await screen.findByRole('heading', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Retained draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByText(/Could not refresh this action item/);
    expect(screen.getByLabelText('Title')).toHaveValue('Retained draft');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(api.actionItems.update).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh current version' }));
    const comparison = await screen.findByRole('region', { name: 'Current saved action item' });
    await waitFor(() => expect(within(comparison).getByText('Current saved details')).toBeVisible());
    expect(screen.getByLabelText('Title')).toHaveValue('Retained draft');
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.actionItems.update).toHaveBeenLastCalledWith(1, expect.objectContaining({ expected_revision: 7, title: 'Retained draft' })));
  });

  it('keeps Cancel available when a conflicted task cannot be reread', async () => {
    vi.mocked(api.actionItems.update).mockRejectedValueOnce(new ApiError('Conflict', 409));
    vi.mocked(api.actionItems.get).mockResolvedValueOnce(actionItem(1)).mockRejectedValueOnce(new ApiError('Deleted', 404));
    renderPage();
    await screen.findByRole('heading', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Retained' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByText(/Could not refresh this action item/);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByLabelText('Title')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Back to action items/ })).toBeEnabled();
  });

  it('uses desired completion/reopen states with the displayed revisions', async () => {
    const complete = actionItem(1, { revision: 2, status: 'completed', completed_at: '2026-10-30T13:00:00Z' });
    vi.mocked(api.actionItems.get).mockResolvedValueOnce(actionItem(1)).mockResolvedValueOnce(complete).mockResolvedValueOnce(actionItem(1, { revision: 3 }));
    renderPage();
    await screen.findByRole('heading', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Mark complete' }));
    await screen.findByRole('button', { name: 'Reopen action item' });
    expect(api.actionItems.update).toHaveBeenNthCalledWith(1, 1, { expected_revision: 1, status: 'completed' });
    fireEvent.click(screen.getByRole('button', { name: 'Reopen action item' }));
    await waitFor(() => expect(api.actionItems.update).toHaveBeenNthCalledWith(2, 1, { expected_revision: 2, status: 'open' }));
  });

  it('resumes polling after a status conflict is reread and successfully retried', async () => {
    vi.useFakeTimers();
    vi.mocked(api.actionItems.update).mockRejectedValueOnce(new ApiError('Conflict', 409));
    vi.mocked(api.actionItems.get).mockResolvedValueOnce(actionItem(1))
      .mockResolvedValueOnce(actionItem(1, { revision: 3 }))
      .mockResolvedValue(actionItem(1, { revision: 4, status: 'completed' }));
    renderPage();
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Mark complete' }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Mark complete' }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole('button', { name: 'Reopen action item' })).toBeEnabled();
    expect(api.actionItems.update).toHaveBeenLastCalledWith(1, { expected_revision: 3, status: 'completed' });
    vi.mocked(api.actionItems.get).mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); });
    expect(api.actionItems.get).toHaveBeenCalledTimes(1);
  });

  it.each(['status', 'delete'] as const)('resumes read-only polling after a %s conflict is reread without another write', async operation => {
    vi.useFakeTimers();
    if (operation === 'status') vi.mocked(api.actionItems.update).mockRejectedValueOnce(new ApiError('Conflict', 409));
    else {
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      vi.mocked(api.actionItems.remove).mockRejectedValueOnce(new ApiError('Conflict', 409));
    }
    vi.mocked(api.actionItems.get).mockResolvedValueOnce(actionItem(1))
      .mockResolvedValueOnce(actionItem(1, { revision: 3, title: 'Current saved task' }))
      .mockResolvedValueOnce(actionItem(1, { revision: 4, title: 'Later agent update' }));
    renderPage();
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole('heading', { name: 'Task 1' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: operation === 'status' ? 'Mark complete' : 'Delete' }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole('heading', { name: 'Current saved task' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Edit' })).toBeEnabled();
    expect(screen.queryByLabelText('Title')).not.toBeInTheDocument();
    vi.mocked(api.actionItems.get).mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); });
    expect(api.actionItems.get).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('heading', { name: 'Later agent update' })).toBeVisible();
    expect(operation === 'status' ? api.actionItems.update : api.actionItems.remove).toHaveBeenCalledTimes(1);
  });

  it('locks the submitted fields and competing actions until saving completes', async () => {
    const saving = deferred<ActionItem>();
    vi.mocked(api.actionItems.update).mockReturnValueOnce(saving.promise);
    renderPage();
    await screen.findByRole('heading', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByLabelText('Title')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
    await act(async () => { saving.resolve(actionItem(1, { revision: 2 })); });
    expect(screen.queryByLabelText('Title')).not.toBeInTheDocument();
  });

  it('confirms deletion and sends its current revision', async () => {
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderPage();
    await screen.findByRole('heading', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(api.actionItems.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(api.actionItems.remove).toHaveBeenCalledWith(1, 1));
    expect(confirmation).toHaveBeenCalledTimes(2);
    expect(navigate).toHaveBeenCalledWith('/action-items');
  });

  it('does not navigate away from a newer page when a pending delete finishes after unmount', async () => {
    const saving = deferred<{ deleted: boolean; id: number }>();
    vi.mocked(api.actionItems.remove).mockReturnValueOnce(saving.promise);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const rendered = renderPage();
    await screen.findByRole('heading', { name: 'Task 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(api.actionItems.remove).toHaveBeenCalledWith(1, 1);
    rendered.unmount();
    await act(async () => { saving.resolve({ deleted: true, id: 1 }); });
    expect(navigate).not.toHaveBeenCalled();
  });
});
