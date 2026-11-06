import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { api, ApiError } from '../../api';
import type {
  ProfileDiscussionTopic,
  ProfileDiscussionTopicPage,
} from '../../api';
import { ProfileDiscussionTopics } from '../ProfileDiscussionTopics';
import { actionItem, deferred } from '../../pages/__tests__/actionItemFixture';
import { POLL_INTERVAL_MS } from '../../constants';

vi.mock('../../api', async (original) => ({
  ...(await original<typeof import('../../api')>()),
  api: {
    profiles: {
      topics: {
        list: vi.fn(),
        get: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        remove: vi.fn(),
        move: vi.fn(),
      },
    },
    actionItems: { list: vi.fn(), update: vi.fn(), move: vi.fn() },
  },
}));
const PID = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
const OTHER = '11111111-2222-4333-8444-555555555555';
const topic = (
  id = 1,
  fields: Partial<ProfileDiscussionTopic> = {},
): ProfileDiscussionTopic => ({
  ...actionItem(id),
  project: null,
  profile_id: PID,
  ...fields,
});
const page = (
  ...items: ProfileDiscussionTopic[]
): ProfileDiscussionTopicPage => ({
  profile_id: PID,
  items,
  total: items.length,
});
const topics = vi.mocked(api.profiles.topics);
const changed = vi.fn();
const reloaded = vi.fn();
function renderTopics(active = true, profileId = PID) {
  return renderWithProviders(
    <ProfileDiscussionTopics
      profileId={profileId}
      active={active}
      disabled={false}
      onBusyChange={changed}
      onReload={reloaded}
    />,
  );
}
const originalModal = Object.getOwnPropertyDescriptor(
  HTMLDialogElement.prototype,
  'showModal',
);
beforeAll(() =>
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.open = true;
    },
  }),
);
afterAll(() => {
  if (originalModal)
    Object.defineProperty(
      HTMLDialogElement.prototype,
      'showModal',
      originalModal,
    );
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal');
});
beforeEach(() => {
  vi.clearAllMocks();
  topics.list.mockResolvedValue(page(topic()));
  topics.get.mockResolvedValue(topic());
  topics.create.mockResolvedValue(topic(2));
  topics.update.mockResolvedValue(topic(1, { revision: 2 }));
  topics.remove.mockResolvedValue({ deleted: true, id: 1 });
  topics.move.mockResolvedValue(topic());
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function edit() {
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Task 1' }));
  await screen.findByLabelText('Notes');
  return screen.getByRole('dialog', { name: 'Edit discussion topic' });
}

describe('ProfileDiscussionTopics', () => {
  it('reads only its scoped queue, displays actual priorities, and loads Markdown notes on demand', async () => {
    renderTopics();
    const title = await screen.findByRole('button', { name: 'Task 1' });
    expect(topics.list).toHaveBeenCalledWith(PID, {
      status: 'open',
      sort: 'manual',
      q: undefined,
      tags: [],
      limit: 10,
      offset: 0,
    });
    expect(
      screen.getByRole('columnheader', { name: 'Tags' }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('Project')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Priority 1')).toBeInTheDocument();
    expect(topics.get).not.toHaveBeenCalled();
    topics.get.mockResolvedValue(
      topic(1, { description: '**Useful** talking point' }),
    );
    fireEvent.click(title);
    expect(await screen.findByText('Useful')).toBeInTheDocument();
    expect(topics.get).toHaveBeenCalledWith(PID, 1);
    expect(api.actionItems.list).not.toHaveBeenCalled();
  });

  it('keeps filtered open topics draggable after the matching results arrive', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderTopics();
    await screen.findByRole('button', { name: 'Task 1' });
    const pending = deferred<ProfileDiscussionTopicPage>();
    topics.list.mockReturnValueOnce(pending.promise);
    fireEvent.change(screen.getByLabelText('Search discussion topics'), {
      target: { value: 'Task' },
    });
    fireEvent.change(screen.getByLabelText('Filter tags'), {
      target: { value: 'security' },
    });
    expect(
      screen.getByRole('button', { name: 'Reorder Task 1' }),
    ).toBeDisabled();
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(
      screen.getByRole('button', { name: 'Reorder Task 1' }),
    ).toBeDisabled();
    await act(async () => {
      pending.resolve(page(topic(1), topic(3), topic(5)));
    });
    expect(
      screen.getByRole('button', { name: 'Reorder Task 5' }),
    ).toBeEnabled();
    expect(topics.list).toHaveBeenLastCalledWith(
      PID,
      expect.objectContaining({ q: 'Task', tags: ['security'] }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Title' }));
    expect(
      screen.queryByRole('button', { name: /^Reorder/ }),
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('columnheader', { name: 'Title' })).toHaveAttribute(
        'aria-sort',
        'ascending',
      ),
    );
  });

  it('completes and reopens using displayed item revisions and a discussion-topic confirmation', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderTopics();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Complete Task 1' }),
    );
    await waitFor(() =>
      expect(topics.update).toHaveBeenCalledWith(PID, 1, {
        expected_revision: 1,
        status: 'completed',
      }),
    );
    expect(confirm).toHaveBeenCalledWith('Complete discussion topic “Task 1”?');
    topics.list.mockResolvedValue(
      page(topic(1, { status: 'completed', revision: 3, priority: null })),
    );
    fireEvent.click(screen.getByRole('tab', { name: 'Completed' }));
    fireEvent.click(
      await screen.findByRole('button', { name: 'Reopen Task 1' }),
    );
    await waitFor(() =>
      expect(topics.update).toHaveBeenLastCalledWith(PID, 1, {
        expected_revision: 3,
        status: 'open',
      }),
    );
    expect(api.actionItems.update).not.toHaveBeenCalled();
  });

  it('creates title, Markdown notes and tags with one UUID and no owner/project fields', async () => {
    renderTopics();
    fireEvent.click(
      await screen.findByRole('button', { name: 'New discussion topic' }),
    );
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: '  Budget review  ' },
    });
    fireEvent.change(screen.getByLabelText('Notes'), {
      target: { value: '## Cost\n\nDiscuss options.' },
    });
    fireEvent.change(screen.getByLabelText('Tags'), {
      target: { value: 'budget, planning' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(topics.create).toHaveBeenCalledWith(PID, {
        title: 'Budget review',
        description: '## Cost\n\nDiscuss options.',
        tags: ['budget', 'planning'],
        request_id: expect.stringMatching(/^[\da-f-]{36}$/),
      }),
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(changed).toHaveBeenCalledWith(true);
  });

  it('freezes uncertain creation and retries the identical UUID and original payload', async () => {
    topics.create.mockRejectedValueOnce(new Error('Connection interrupted'));
    renderTopics();
    fireEvent.click(
      await screen.findByRole('button', { name: 'New discussion topic' }),
    );
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Original topic' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByText('Connection interrupted');
    const original = topics.create.mock.calls[0][1];
    for (const field of ['Title', 'Notes', 'Tags'])
      expect(screen.getByLabelText(field)).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(topics.create).toHaveBeenCalledTimes(2));
    expect(topics.create.mock.calls[1][1]).toEqual(original);
  });

  it('unlocks a validation failure and uses a new UUID for its corrected draft', async () => {
    topics.create.mockRejectedValueOnce(new ApiError('Invalid tags', 422));
    renderTopics();
    fireEvent.click(
      await screen.findByRole('button', { name: 'New discussion topic' }),
    );
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Original' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByText('Invalid tags');
    const requestId = topics.create.mock.calls[0][1].request_id;
    expect(screen.getByLabelText('Title')).toBeEnabled();
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Corrected' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(topics.create).toHaveBeenCalledTimes(2));
    expect(topics.create.mock.calls[1][1].request_id).not.toBe(requestId);
  });

  it('edits the captured full-record revision and sends explicit notes/tag clears', async () => {
    topics.get.mockResolvedValue(topic(1, { revision: 5 }));
    renderTopics();
    await edit();
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Tags'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(topics.update).toHaveBeenCalledWith(PID, 1, {
        title: 'Task 1',
        description: '',
        tags: [],
        expected_revision: 5,
      }),
    );
  });

  it('retains conflict drafts and blocks retries until the current item is successfully reread', async () => {
    topics.get
      .mockResolvedValueOnce(topic(1, { revision: 3 }))
      .mockRejectedValueOnce(new Error('Reread failed'));
    topics.update.mockRejectedValueOnce(new ApiError('Changed', 409));
    renderTopics();
    await edit();
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Retained draft' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByRole('button', { name: 'Retry refresh' });
    expect(screen.getByLabelText('Title')).toHaveValue('Retained draft');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    topics.get.mockResolvedValue(
      topic(1, { revision: 7, title: 'Current saved title' }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Retry refresh' }));
    expect(await screen.findByText('Current saved title')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(topics.update).toHaveBeenLastCalledWith(
        PID,
        1,
        expect.objectContaining({
          title: 'Retained draft',
          expected_revision: 7,
        }),
      ),
    );
  });

  it('deletes with the displayed revision only after confirmation', async () => {
    vi.spyOn(window, 'confirm')
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    topics.get.mockResolvedValue(topic(1, { revision: 4 }));
    renderTopics();
    await edit();
    fireEvent.click(screen.getByRole('button', { name: 'Delete topic' }));
    expect(topics.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete topic' }));
    await waitFor(() => expect(topics.remove).toHaveBeenCalledWith(PID, 1, 4));
  });

  it('requires a post-conflict reread when a newer read finished during a pending save', async () => {
    const pending = deferred<ProfileDiscussionTopic>();
    topics.update.mockReturnValueOnce(pending.promise);
    topics.get
      .mockResolvedValueOnce(topic(1, { revision: 3 }))
      .mockResolvedValueOnce(topic(1, { revision: 5 }))
      .mockRejectedValueOnce(new Error('Post-conflict refresh failed'));
    const rendered = renderTopics();
    await edit();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    rendered.rerender(
      <ProfileDiscussionTopics
        profileId={PID}
        active={false}
        disabled={false}
        onBusyChange={changed}
        onReload={reloaded}
      />,
    );
    rendered.rerender(
      <ProfileDiscussionTopics
        profileId={PID}
        active
        disabled={false}
        onBusyChange={changed}
        onReload={reloaded}
      />,
    );
    await waitFor(() => expect(topics.get).toHaveBeenCalledTimes(2));
    await act(async () => {
      pending.reject(new ApiError('Changed during save', 409));
    });
    await screen.findByRole('button', { name: 'Retry refresh' });
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Delete topic' })).toBeDisabled();
    expect(topics.update).toHaveBeenCalledTimes(1);
  });

  it('keeps deletion bound to the retained draft until a conflict exposes the current saved version', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    topics.get
      .mockResolvedValueOnce(topic(1, { revision: 3 }))
      .mockResolvedValueOnce(
        topic(1, { revision: 5, description: 'Updated saved notes' }),
      )
      .mockResolvedValueOnce(
        topic(1, { revision: 5, description: 'Updated saved notes' }),
      );
    topics.remove.mockRejectedValueOnce(new ApiError('Topic changed', 409));
    const rendered = renderTopics();
    await edit();
    fireEvent.change(screen.getByLabelText('Notes'), {
      target: { value: 'Retained original draft' },
    });
    rendered.rerender(
      <ProfileDiscussionTopics
        profileId={PID}
        active={false}
        disabled={false}
        onBusyChange={changed}
        onReload={reloaded}
      />,
    );
    rendered.rerender(
      <ProfileDiscussionTopics
        profileId={PID}
        active
        disabled={false}
        onBusyChange={changed}
        onReload={reloaded}
      />,
    );
    await waitFor(() => expect(topics.get).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Delete topic' }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Delete topic' }));
    await waitFor(() =>
      expect(topics.remove).toHaveBeenNthCalledWith(1, PID, 1, 3),
    );
    expect(await screen.findByText('Updated saved notes')).toBeInTheDocument();
    expect(screen.getByLabelText('Notes')).toHaveValue(
      'Retained original draft',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Delete topic' }));
    await waitFor(() =>
      expect(topics.remove).toHaveBeenNthCalledWith(2, PID, 1, 5),
    );
  });

  it('removes hidden modal DOM and pauses polling while retaining the draft for return', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const rendered = renderTopics();
    await edit();
    fireEvent.change(screen.getByLabelText('Notes'), {
      target: { value: 'Retained across tabs' },
    });
    rendered.rerender(
      <ProfileDiscussionTopics
        profileId={PID}
        active={false}
        disabled={false}
        onBusyChange={changed}
        onReload={reloaded}
      />,
    );
    expect(
      screen.queryByRole('dialog', { hidden: true }),
    ).not.toBeInTheDocument();
    topics.list.mockClear();
    topics.get.mockClear();
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 2);
    });
    expect(topics.list).not.toHaveBeenCalled();
    expect(topics.get).not.toHaveBeenCalled();
    rendered.rerender(
      <ProfileDiscussionTopics
        profileId={PID}
        active
        disabled={false}
        onBusyChange={changed}
        onReload={reloaded}
      />,
    );
    expect(await screen.findByLabelText('Notes')).toHaveValue(
      'Retained across tabs',
    );
  });

  it.each([
    { profile_id: OTHER, items: [], total: 0 },
    { profile_id: PID, items: [topic(1, { profile_id: OTHER })], total: 1 },
  ])(
    'rejects owner mismatch before rendering rows or enabling writes: %j',
    async (result) => {
      topics.list.mockResolvedValue(result);
      renderTopics();
      await screen.findByRole('button', { name: 'Reload profile' });
      expect(reloaded).toHaveBeenCalled();
      expect(
        screen.queryByRole('button', { name: 'Task 1' }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'New discussion topic' }),
      ).toBeDisabled();
    },
  );

  it('retains the draft but blocks writes if the parent becomes unavailable', async () => {
    const rendered = renderTopics();
    await edit();
    fireEvent.change(screen.getByLabelText('Notes'), {
      target: { value: 'Retained during parent refresh failure' },
    });
    rendered.rerender(
      <ProfileDiscussionTopics
        profileId={PID}
        active
        disabled
        onBusyChange={changed}
        onReload={reloaded}
      />,
    );
    expect(screen.getByLabelText('Notes')).toHaveValue(
      'Retained during parent refresh failure',
    );
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Delete topic' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled();
    fireEvent.submit(
      screen.getByRole('button', { name: 'Save' }).closest('form')!,
    );
    expect(topics.update).not.toHaveBeenCalled();
  });

  it('visibly disables queue actions while another profile editor is busy', async () => {
    const rendered = renderTopics();
    await screen.findByRole('button', { name: 'Task 1' });
    rendered.rerender(
      <ProfileDiscussionTopics
        profileId={PID}
        active
        disabled
        onBusyChange={changed}
        onReload={reloaded}
      />,
    );
    for (const name of [
      'Task 1',
      'Complete Task 1',
      'Edit Task 1',
      'Reorder Task 1',
    ])
      expect(screen.getByRole('button', { name })).toBeDisabled();
  });

  it('does not reread or change another profile after an unmounted save completes', async () => {
    const pending = deferred<ProfileDiscussionTopic>();
    topics.create.mockReturnValueOnce(pending.promise);
    const rendered = renderTopics();
    fireEvent.click(
      await screen.findByRole('button', { name: 'New discussion topic' }),
    );
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Pending original profile' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    rendered.unmount();
    topics.list.mockClear();
    reloaded.mockClear();
    await act(async () => {
      pending.resolve(topic(2));
    });
    expect(topics.list).not.toHaveBeenCalled();
    expect(reloaded).not.toHaveBeenCalled();
  });
});

it('sorts all discussion columns on the server, excludes global fields, and restores manual order', async () => {
  renderTopics();
  await screen.findByRole('button', { name: 'Task 1' });
  expect(
    screen.queryByRole('combobox', { name: 'Sort' }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: 'Project' }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: 'Due date' }),
  ).not.toBeInTheDocument();
  for (const [label, first, second] of [
    ['Title', 'title', 'title_desc'],
    ['Tags', 'tags_asc', 'tags_desc'],
    ['Updated', 'updated', 'updated_asc'],
    ['Priority', 'manual', 'manual_desc'],
  ]) {
    fireEvent.click(screen.getByRole('button', { name: label }));
    await waitFor(() =>
      expect(topics.list).toHaveBeenLastCalledWith(
        PID,
        expect.objectContaining({ sort: first, offset: 0 }),
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: label }));
    await waitFor(() =>
      expect(topics.list).toHaveBeenLastCalledWith(
        PID,
        expect.objectContaining({ sort: second, offset: 0 }),
      ),
    );
  }
  expect(
    screen.queryByRole('button', { name: /^Reorder/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Priority' }));
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Reorder Task 1' }),
    ).toBeEnabled(),
  );
  expect(topics.move).not.toHaveBeenCalled();
  expect(topics.update).not.toHaveBeenCalled();
});


it('resets a real page-two discussion topic read before requesting a new column order', async () => {
  topics.list.mockImplementation(async (_id, filters) => ({ profile_id: PID, items: [topic(filters?.offset ? 11 : 1)], total: 30 }));
  renderTopics();
  await screen.findByRole('button', { name: 'Task 1' });
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await screen.findByRole('button', { name: 'Task 11' });
  const before = topics.list.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Tags' }));
  await waitFor(() => expect(screen.getByRole('columnheader', { name: 'Tags' })).toHaveAttribute('aria-sort', 'ascending'));
  expect(topics.list.mock.calls.slice(before)).toEqual([[PID, expect.objectContaining({ sort: 'tags_asc', offset: 0, limit: 10 })]]);
  expect(screen.getByRole('button', { name: 'Task 1' })).toBeInTheDocument();
  expect(screen.queryByText(/Loading discussion topics|To drag topics/)).not.toBeInTheDocument();
  expect(topics.update).not.toHaveBeenCalled();
  expect(topics.move).not.toHaveBeenCalled();
});
