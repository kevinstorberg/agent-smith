import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router';
import { renderWithProviders } from '../../test-utils';
import { ActionItemDetailPage } from '../ActionItemDetailPage';
import { ActionItemsIndexPage } from '../ActionItemsIndexPage';
import { actionItem, deferred } from './actionItemFixture';
import { defaultView, mergeViewCookie } from '../../utils/viewPreferences';
import { ActionItemDeadlineWindow } from '../../components/ActionItemDeadlines';

vi.mock('../../api', async (original) => {
  const actual = await original<typeof import('../../api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      actionItems: {
        list: vi.fn(),
        get: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        remove: vi.fn(),
        move: vi.fn(),
      },
      actionItemProjects: { list: vi.fn(), create: vi.fn(), remove: vi.fn() },
    },
  };
});
import { api, ApiError } from '../../api';

const precise = '2026-07-01T13:15:30.123456+00:00';
const rows = [
  actionItem(1, { due_at: precise }),
  actionItem(2, { due_at: null }),
];

function renderPage(path = '/action-items') {
  return renderWithProviders(
    <Routes>
      <Route path="/action-items" element={<ActionItemsIndexPage />} />
      <Route path="/action-items/new" element={<ActionItemDetailPage />} />
      <Route path="/action-items/:id" element={<ActionItemDetailPage />} />
    </Routes>,
    { initialEntries: [path] },
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.mocked(api.actionItems.list).mockResolvedValue({
    items: rows,
    total: rows.length,
  });
  vi.mocked(api.actionItems.get).mockResolvedValue(rows[0]);
  vi.mocked(api.actionItems.create).mockResolvedValue(actionItem(3));
  vi.mocked(api.actionItems.update).mockResolvedValue(
    actionItem(1, { revision: 2 }),
  );
  vi.mocked(api.actionItemProjects.list).mockResolvedValue({
    items: [{ id: 1, name: 'Work', created_at: '2026-11-01T00:00:00Z' }],
    total: 1,
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('local deadline drafts', () => {
  it('sends a local date and time as a UTC instant while retaining the selected project and UUID', async () => {
    renderPage('/action-items/new?project=Work');
    const deadline = await screen.findByLabelText('Due date and time');
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Timed task' },
    });
    fireEvent.change(deadline, { target: { value: '2026-12-01T09:15' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.actionItems.create).toHaveBeenCalledWith(
        expect.objectContaining({
          due_at: new Date(2026, 11, 1, 9, 15).toISOString(),
          project: 'Work',
          request_id: expect.any(String),
        }),
      ),
    );
  });

  it('keeps an exact saved microsecond timestamp when an unrelated title changes', async () => {
    renderPage('/action-items/1?edit=1');
    expect(await screen.findByLabelText('Due date and time')).not.toHaveValue(
      '',
    );
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Only title' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.actionItems.update).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          title: 'Only title',
          due_at: precise,
          expected_revision: 1,
        }),
      ),
    );
  });

  it('clears an existing deadline explicitly without altering other fields', async () => {
    renderPage('/action-items/1?edit=1');
    const deadline = await screen.findByLabelText('Due date and time');
    fireEvent.change(deadline, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.actionItems.update).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          due_at: null,
          title: 'Task 1',
          project: 'Work',
          expected_revision: 1,
        }),
      ),
    );
  });

  it('keeps undated callers unchanged when no deadline is entered', async () => {
    renderPage('/action-items/new');
    expect(await screen.findByLabelText('Due date and time')).toHaveValue('');
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Undated task' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.actionItems.create).toHaveBeenCalledTimes(1),
    );
    expect(
      vi.mocked(api.actionItems.create).mock.calls[0][0],
    ).not.toHaveProperty('due_at');
  });

  it('freezes the original deadline and UUID after an uncertain create', async () => {
    vi.mocked(api.actionItems.create).mockRejectedValueOnce(
      new Error('Uncertain deadline save'),
    );
    renderPage('/action-items/new');
    const deadline = await screen.findByLabelText('Due date and time');
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Frozen deadline' },
    });
    fireEvent.change(deadline, { target: { value: '2026-12-01T09:15' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByRole('alert');
    const original = vi.mocked(api.actionItems.create).mock.calls[0][0];
    expect(deadline).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.actionItems.create).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(api.actionItems.create).mock.calls[1][0]).toEqual(
      original,
    );
    expect(original.due_at).toBe(new Date(2026, 11, 1, 9, 15).toISOString());
  });

  it('retains deadline drafts across CAS refresh and displays the current saved deadline for review', async () => {
    const fresh = deferred<(typeof rows)[0]>();
    vi.mocked(api.actionItems.get)
      .mockResolvedValueOnce(rows[0])
      .mockReturnValueOnce(fresh.promise);
    vi.mocked(api.actionItems.update).mockRejectedValueOnce(
      new ApiError('Changed', 409),
    );
    renderPage('/action-items/1?edit=1');
    const deadline = await screen.findByLabelText('Due date and time');
    fireEvent.change(deadline, { target: { value: '2026-12-01T09:15' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Your draft is retained/,
    );
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    await act(async () => {
      fresh.resolve(
        actionItem(1, { revision: 3, due_at: '2027-01-02T15:00:00Z' }),
      );
    });
    const comparison = screen.getByRole('region', {
      name: 'Current saved action item',
    });
    expect(within(comparison).getByText(/2027/)).toBeVisible();
    expect(deadline).toHaveValue('2026-12-01T09:15');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.actionItems.update).toHaveBeenLastCalledWith(
        1,
        expect.objectContaining({
          expected_revision: 3,
          due_at: new Date(2026, 11, 1, 9, 15).toISOString(),
        }),
      ),
    );
  });
});

describe('independent deadline window', () => {
  it('clears an old numeric validation notice when another saved view changes the hours', async () => {
    const onChange = vi.fn();
    const rendered = render(
      <ActionItemDeadlineWindow
        hours={24}
        onChange={onChange}
        disabled={false}
      />,
    );
    const hours = screen.getByRole('spinbutton', { name: 'Hours' });
    fireEvent.change(hours, { target: { value: '169' } });
    fireEvent.blur(hours);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'current window remains 24 hours',
    );
    rendered.rerender(
      <ActionItemDeadlineWindow
        hours={48}
        onChange={onChange}
        disabled={false}
      />,
    );
    await waitFor(() =>
      expect(screen.queryByRole('alert')).not.toBeInTheDocument(),
    );
    expect(hours).toHaveValue(48);
    expect(onChange).not.toHaveBeenCalled();
  });
  it('shows saved deadlines while keeping undated tasks visible by default', async () => {
    renderPage();
    expect(await screen.findByRole('button', { name: 'Task 2' })).toBeVisible();
    expect(await screen.findByText(/2026/)).toBeVisible();
    expect(
      screen.getByRole('checkbox', { name: 'Deadline window' }),
    ).not.toBeChecked();
    expect(
      vi.mocked(api.actionItems.list).mock.lastCall?.[0],
    ).not.toHaveProperty('due_within_hours');
  });

  it('applies adjustable hours independently of project, status and tags, then restores undated results', async () => {
    renderPage('/action-items?project=Work&status=completed&tags=security');
    const enabled = await screen.findByRole('checkbox', {
      name: 'Deadline window',
    });
    fireEvent.click(enabled);
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({
          due_within_hours: 24,
          project: 'Work',
          status: 'completed',
          tags: ['security'],
          offset: 0,
        }),
      ),
    );
    const slider = screen.getByRole('slider', { name: 'Upcoming hours' });
    for (const value of [5, 48]) {
      fireEvent.change(slider, { target: { value: String(value) } });
      await waitFor(() =>
        expect(api.actionItems.list).toHaveBeenLastCalledWith(
          expect.objectContaining({
            due_within_hours: value,
            project: 'Work',
            status: 'completed',
            tags: ['security'],
          }),
        ),
      );
    }
    expect(screen.getByText(/Past deadlines/)).toBeVisible();
    fireEvent.click(enabled);
    await waitFor(() =>
      expect(
        vi.mocked(api.actionItems.list).mock.lastCall?.[0],
      ).not.toHaveProperty('due_within_hours'),
    );
    expect(screen.getByRole('tab', { name: 'Work' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('does not send invalid hours while the numeric control is being edited', async () => {
    renderPage('/action-items?due_within_hours=24');
    const hours = await screen.findByRole('spinbutton', { name: 'Hours' });
    await waitFor(() => expect(api.actionItems.list).toHaveBeenCalledTimes(1));
    fireEvent.change(hours, { target: { value: '' } });
    fireEvent.blur(hours);
    expect(hours).toHaveValue(24);
    expect(api.actionItems.list).toHaveBeenCalledTimes(1);
    fireEvent.change(hours, { target: { value: '169' } });
    fireEvent.blur(hours);
    expect(hours).toHaveValue(24);
    expect(api.actionItems.list).toHaveBeenCalledTimes(1);
  });

  it('restores the hours window before the first request and allows an explicit URL to clear it', async () => {
    document.cookie = mergeViewCookie('', 'actionItems', {
      ...defaultView('actionItems'),
      due_within_hours: 48,
      project: 'Work',
      tags: 'security',
    });
    const rendered = renderPage();
    expect(
      await screen.findByRole('checkbox', { name: 'Deadline window' }),
    ).toBeChecked();
    expect(api.actionItems.list).toHaveBeenCalledWith(
      expect.objectContaining({
        due_within_hours: 48,
        project: 'Work',
        tags: ['security'],
      }),
    );
    rendered.unmount();
    renderPage('/action-items?due_within_hours=');
    expect(
      await screen.findByRole('checkbox', { name: 'Deadline window' }),
    ).not.toBeChecked();
    await waitFor(() =>
      expect(
        vi.mocked(api.actionItems.list).mock.lastCall?.[0],
      ).not.toHaveProperty('due_within_hours'),
    );
  });

  it('cannot commit a late response for an earlier hours window', async () => {
    renderPage('/action-items?due_within_hours=24');
    const slider = await screen.findByRole('slider', {
      name: 'Upcoming hours',
    });
    const old = deferred<{ items: typeof rows; total: number }>();
    vi.mocked(api.actionItems.list)
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce({ items: [rows[1]], total: 1 });
    fireEvent.change(slider, { target: { value: '5' } });
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ due_within_hours: 5 }),
      ),
    );
    fireEvent.change(slider, { target: { value: '48' } });
    await waitFor(() =>
      expect(api.actionItems.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ due_within_hours: 48 }),
      ),
    );
    await act(async () => {
      old.resolve({ items: [rows[0]], total: 1 });
    });
    expect(
      screen.queryByRole('button', { name: 'Task 1' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Task 2' })).toBeVisible();
  });
});
