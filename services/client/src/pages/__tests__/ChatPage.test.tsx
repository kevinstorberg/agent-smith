import { defaultView, mergeViewCookie, readViewCookie } from '../../utils/viewPreferences';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, type ChatMessage, type ChatRoom, type ChatRoomDetail } from '../../api';
import { renderWithProviders } from '../../test-utils';
import { ChatPage } from '../ChatPage';

vi.mock('../../api', () => ({
  api: {
    chat: {
      list: vi.fn(),
      create: vi.fn(),
      get: vi.fn(),
      postMessage: vi.fn(),
      stop: vi.fn(),
      config: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
    },
  },
}));

// Fixture values for the mocked /chat/config response — the page itself never
// hardcodes participant names; it renders whatever the backend registry returns.
const AI_PARTICIPANTS = ['Kimi', 'Qwen'];

const room: ChatRoom = {
  id: 42,
  topic: 'Choose a cache strategy',
  context: 'Keep it small.',
  state: 'open',
  created_at: '2026-09-09T12:00:00Z',
  updated_at: '2026-09-09T12:00:00Z',
  closed_at: null,
};

const detail: ChatRoomDetail = {
  room,
  messages: [{
    id: 7,
    room_id: 42,
    author: 'codex',
    body: 'Extend the existing cache interface.',
    created_at: '2026-09-09T12:01:00Z',
  }],
  last_message_id: 7,
  has_more: false,
};

function message(id: number, roomId = room.id): ChatMessage {
  return { ...detail.messages[0], id, room_id: roomId, body: `Message ${id}` };
}

beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.mocked(api.chat.list).mockResolvedValue({ items: [room], total: 1 });
  vi.mocked(api.chat.get).mockResolvedValue(detail);
  vi.mocked(api.chat.config).mockResolvedValue({ participants: AI_PARTICIPANTS });
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('ChatPage', () => {
  it('restores room-list preferences before requesting and keeps room drafts out of saved settings', async () => {
    document.cookie = mergeViewCookie('', 'chat', { ...defaultView('chat'), q: 'cache', status: 'closed', sort: 'name', limit: 25, offset: 50 });
    vi.mocked(api.chat.list).mockResolvedValue({ items: [room], total: 100 });
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });
    await screen.findByText(detail.messages[0].body);
    expect(api.chat.list).toHaveBeenCalledTimes(1);
    expect(api.chat.list).toHaveBeenCalledWith({ q: 'cache', status: 'closed', sort: 'name', limit: 25, offset: 50 });
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Unsent draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Reset view' }));
    await waitFor(() => expect(api.chat.list).toHaveBeenLastCalledWith({ q: undefined, status: undefined, sort: 'updated', limit: 10, offset: 0 }));
    expect(screen.getByLabelText('Message')).toHaveValue('Unsent draft');
    expect(screen.getByRole('heading', { name: room.topic })).toBeInTheDocument();
    expect(readViewCookie(document.cookie)).toEqual([]);
  });

  it('keeps search, status and sort available while loading, empty and failed', async () => {
    vi.mocked(api.chat.list).mockRejectedValueOnce(new Error('private server diagnostic'));
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });
    expect(screen.getByRole('textbox', { name: 'Search rooms' })).toBeVisible();
    expect(screen.getByRole('combobox', { name: 'Room status' })).toHaveValue('all');
    expect(screen.getByRole('combobox', { name: 'Sort rooms' })).toHaveValue('updated');
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load rooms.');
    expect(screen.queryByText('private server diagnostic')).not.toBeInTheDocument();
    vi.mocked(api.chat.list).mockResolvedValue({ items: [], total: 0 });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('No rooms yet.');
    expect(screen.getByRole('combobox', { name: 'Room status' })).toBeVisible();
  });

  it('debounces room search and combines status and sort before paging without replacing the selected room', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.chat.list).mockResolvedValue({ items: [room], total: 25 });
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });
    await screen.findByText(detail.messages[0].body);
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Keep my current draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(api.chat.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 })));
    const otherRoom = { ...room, id: 43, topic: 'Another result', state: 'closed' as const };
    vi.mocked(api.chat.list).mockResolvedValue({ items: [otherRoom], total: 1 }).mockClear();
    const input = screen.getByRole('textbox', { name: 'Search rooms' });
    input.focus();
    fireEvent.change(input, { target: { value: ' cache ' } });
    await act(async () => { vi.advanceTimersByTime(299); });
    expect(api.chat.list).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(api.chat.list).toHaveBeenCalledTimes(1);
    expect(api.chat.list).toHaveBeenCalledWith({ limit: 10, offset: 0, q: 'cache', status: undefined, sort: 'updated' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Room status' }), { target: { value: 'closed' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort rooms' }), { target: { value: 'name' } });
    await waitFor(() => expect(api.chat.list).toHaveBeenLastCalledWith({ limit: 10, offset: 0, q: 'cache', status: 'closed', sort: 'name' }));
    expect(screen.getByRole('heading', { name: room.topic })).toBeInTheDocument();
    expect(screen.getByLabelText('Message')).toHaveValue('Keep my current draft');
    expect(await screen.findByText('The selected room is outside the current results.')).toBeInTheDocument();
    expect(input).toHaveFocus();
  });

  it('ignores a stale room list response after newer search results arrive', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });
    await screen.findByText(detail.messages[0].body);
    let finish!: (result: { items: ChatRoom[]; total: number }) => void;
    vi.mocked(api.chat.list).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Search rooms' }), { target: { value: 'old' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    const current = { ...room, id: 43, topic: 'Current room result' };
    vi.mocked(api.chat.list).mockResolvedValue({ items: [current], total: 1 });
    fireEvent.change(screen.getByRole('textbox', { name: 'Search rooms' }), { target: { value: 'current' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    await screen.findByRole('button', { name: /Current room result/ });
    await act(async () => { finish({ items: [{ ...room, id: 44, topic: 'Stale room result' }], total: 1 }); });
    expect(screen.queryByRole('button', { name: /Stale room result/ })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: room.topic })).toBeInTheDocument();
  });

  it('loads rooms and the selected transcript', async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });

    expect(await screen.findByText('Choose a cache strategy')).toBeInTheDocument();
    expect(await screen.findByText('Extend the existing cache interface.')).toBeInTheDocument();
    expect(screen.getByText('Keep it small.')).toBeInTheDocument();
  });

  it('creates a room from topic and optional context', async () => {
    const created = { ...room, id: 43, topic: 'New topic' };
    vi.mocked(api.chat.create).mockResolvedValue(created);
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });

    await screen.findByText('Choose a cache strategy');
    fireEvent.click(screen.getByText('+ New Room'));
    fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'New topic' } });
    fireEvent.change(screen.getByLabelText('Context (optional)'), { target: { value: 'One constraint' } });
    fireEvent.click(screen.getByText('Create Room'));

    await waitFor(() => expect(api.chat.create).toHaveBeenCalledWith({
      topic: 'New topic',
      context: 'One constraint',
    }));
  });

  it('posts dashboard messages as the User contract', async () => {
    vi.mocked(api.chat.postMessage).mockResolvedValue({
      id: 8,
      room_id: 42,
      author: 'user',
      body: 'Please compare both options.',
      created_at: '2026-09-09T12:02:00Z',
    });
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });

    await screen.findByText('Extend the existing cache interface.');
    fireEvent.change(screen.getByLabelText('Message'), {
      target: { value: 'Please compare both options.' },
    });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => expect(api.chat.postMessage).toHaveBeenCalledWith(
      42,
      'Please compare both options.',
    ));
    expect(await screen.findByText('Please compare both options.')).toBeInTheDocument();
  });

  it('copies one universal invite for the selected room', async () => {
    const otherRoom = { ...room, id: 43, topic: 'Compare queues' };
    vi.mocked(api.chat.list).mockResolvedValue({ items: [room, otherRoom], total: 2 });
    vi.mocked(api.chat.get).mockImplementation(async id => ({
      ...detail,
      room: id === otherRoom.id ? otherRoom : room,
    }));
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });

    await screen.findByText('Extend the existing cache interface.');
    expect(screen.getAllByRole('button', { name: 'Copy' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

    expect(navigator.clipboard.writeText).toHaveBeenLastCalledWith(
      'Join Agent Smith chat room 42 using the chat MCP tools. Collaborate until the room closes.',
    );

    fireEvent.click(screen.getByRole('button', { name: /Compare queues/ }));
    await screen.findByRole('heading', { name: 'Compare queues' });
    fireEvent.click(screen.getByRole('button', { name: /Copy|Copied/ }));
    expect(navigator.clipboard.writeText).toHaveBeenLastCalledWith(
      'Join Agent Smith chat room 43 using the chat MCP tools. Collaborate until the room closes.',
    );
  });

  it('stops agent access with one confirmed action', async () => {
    const closed = {
      ...room,
      state: 'closed' as const,
      closed_at: '2026-09-09T12:03:00Z',
    };
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(api.chat.stop).mockResolvedValue(closed);
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });

    fireEvent.click(await screen.findByText('Stop Agent Access'));

    await waitFor(() => expect(api.chat.stop).toHaveBeenCalledWith(42));
    expect(await screen.findByText('Agent Access Stopped')).toBeDisabled();
    expect(screen.getByLabelText('Message')).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Copy|Copied/ })).not.toBeInTheDocument();
  });

  it('renders configured AI participant messages with their byline', async () => {
    const participant = AI_PARTICIPANTS[0];
    vi.mocked(api.chat.get).mockResolvedValue({
      ...detail,
      messages: [
        ...detail.messages,
        {
          id: 9,
          room_id: 42,
          author: participant,
          body: 'I would benchmark both caches first.',
          created_at: '2026-09-09T12:04:00Z',
        },
      ],
      last_message_id: 9,
    });
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });

    const body = await screen.findByText('I would benchmark both caches first.');
    expect(body.closest('article')).toHaveClass(`chat-message-${participant}`);
    expect(screen.getByText(participant)).toBeInTheDocument();
  });

  it('offers an AI mention hint but never an AI invite button', async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });

    const mentionList = AI_PARTICIPANTS.map(name => `@${name}`).join(' or ');
    expect(
      await screen.findByText(`Mention ${mentionList} to bring an AI into the room.`),
    ).toBeInTheDocument();
    const invites = screen.getByText('Invite an agent:').parentElement!;
    for (const name of AI_PARTICIPANTS) {
      expect(invites).not.toHaveTextContent(name);
    }
  });

  it('edits a room from the header form', async () => {
    const renamed = { ...room, topic: 'Renamed topic', context: 'New context' };
    vi.mocked(api.chat.update).mockResolvedValue(renamed);
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });

    await screen.findByText('Extend the existing cache interface.');
    fireEvent.click(screen.getByText('Edit'));
    fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'Renamed topic' } });
    fireEvent.change(screen.getByLabelText('Context (optional)'), { target: { value: 'New context' } });
    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => expect(api.chat.update).toHaveBeenCalledWith(42, {
      topic: 'Renamed topic',
      context: 'New context',
    }));
    expect(await screen.findByRole('heading', { name: 'Renamed topic' })).toBeInTheDocument();
  });

  it('deletes a room after one confirmed action', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(api.chat.remove).mockImplementation(async () => {
      vi.mocked(api.chat.list).mockResolvedValue({ items: [], total: 0 });
      return undefined;
    });
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });

    await screen.findByText('Extend the existing cache interface.');
    fireEvent.click(screen.getByText('Delete'));

    await waitFor(() => expect(api.chat.remove).toHaveBeenCalledWith(42));
    await waitFor(() => expect(screen.queryByText('Choose a cache strategy')).not.toBeInTheDocument());
  });

  it('polls without issuing overlapping state machinery', async () => {
    vi.useFakeTimers();
    await act(async () => { renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] }); });
    vi.mocked(api.chat.list).mockClear();
    vi.mocked(api.chat.get).mockClear();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });

    expect(api.chat.list).toHaveBeenCalledTimes(1);
    expect(api.chat.get).toHaveBeenCalledTimes(1);
  });

  it('polls the current room list criteria while retaining the selected transcript cursor', async () => {
    vi.useFakeTimers();
    await act(async () => { renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] }); });
    await act(async () => {
      fireEvent.change(screen.getByRole('textbox', { name: 'Search rooms' }), { target: { value: 'cache' } });
      fireEvent.change(screen.getByRole('combobox', { name: 'Room status' }), { target: { value: 'open' } });
      fireEvent.change(screen.getByRole('combobox', { name: 'Sort rooms' }), { target: { value: 'name' } });
      await vi.advanceTimersByTimeAsync(300);
    });
    vi.mocked(api.chat.list).mockClear();
    vi.mocked(api.chat.get).mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(api.chat.list).toHaveBeenCalledTimes(1);
    expect(api.chat.list).toHaveBeenCalledWith({ limit: 10, offset: 0, q: 'cache', status: 'open', sort: 'name' });
    expect(api.chat.get).toHaveBeenCalledWith(42, 7);
  });

  it.each(['update', 'stop'] as const)('ignores a delayed room %s after selecting another room', async action => {
    const otherRoom = { ...room, id: 43, topic: 'Another room' };
    let finish!: (value: ChatRoom) => void;
    vi.mocked(api.chat.list).mockResolvedValue({ items: [room, otherRoom], total: 2 });
    vi.mocked(api.chat.get).mockImplementation(async id => id === 42 ? detail
      : { ...detail, room: otherRoom, messages: [message(20, 43)], last_message_id: 20 });
    vi.mocked(api.chat[action]).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });
    await screen.findByText(detail.messages[0].body);
    if (action === 'update') {
      fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
      fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'Old room updated' } });
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    } else fireEvent.click(screen.getByRole('button', { name: 'Stop Agent Access' }));
    fireEvent.click(screen.getByRole('button', { name: /Another room/ }));
    await screen.findByText('Message 20');
    await act(async () => { finish({ ...room, topic: 'Old room updated', state: action === 'stop' ? 'closed' : 'open' }); });
    expect(screen.getByRole('heading', { name: otherRoom.topic })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Old room updated' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Message')).toBeEnabled();
  });

  it('continues beyond the first page without skipping replies after a local send', async () => {
    vi.useFakeTimers();
    const firstPage = Array.from({ length: 100 }, (_, index) => message(index + 1));
    vi.mocked(api.chat.get)
      .mockResolvedValueOnce({ ...detail, messages: firstPage, last_message_id: 100, has_more: true })
      .mockResolvedValueOnce({ ...detail, messages: [message(101), message(102)], last_message_id: 102 });
    vi.mocked(api.chat.postMessage).mockResolvedValue(message(102));
    await act(async () => { renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] }); });
    expect(screen.getByText('Loading more messages...')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'A local send' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Send' })); });
    expect(screen.getByText('Message 102')).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });

    expect(api.chat.get).toHaveBeenNthCalledWith(1, 42, 0);
    expect(api.chat.get).toHaveBeenNthCalledWith(2, 42, 100);
    const messages = screen.getByRole('region', { name: 'Chat messages' }).querySelectorAll('.chat-message-body');
    expect(messages).toHaveLength(102);
    expect([...messages].slice(-3).map(element => element.textContent)).toEqual(['Message 100', 'Message 101', 'Message 102']);
    expect(screen.queryByText('Loading more messages...')).not.toBeInTheDocument();
  });

  it('ignores a delayed read after switching rooms', async () => {
    const otherRoom = { ...room, id: 43, topic: 'Another room' };
    let resolve!: (value: ChatRoomDetail) => void;
    vi.mocked(api.chat.list).mockResolvedValue({ items: [room, otherRoom], total: 2 });
    vi.mocked(api.chat.get).mockImplementation(id => id === 42
      ? new Promise(done => { resolve = done; })
      : Promise.resolve({ ...detail, room: otherRoom, messages: [message(20, 43)], last_message_id: 20 }));
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });
    await waitFor(() => expect(api.chat.get).toHaveBeenCalledWith(42, 0));
    fireEvent.click(screen.getByRole('button', { name: /Another room/ }));
    await screen.findByText('Message 20');

    await act(async () => { resolve(detail); });

    expect(screen.getByRole('heading', { name: 'Another room' })).toBeInTheDocument();
    expect(screen.getByText('Message 20')).toBeInTheDocument();
    expect(screen.queryByText(detail.messages[0].body)).not.toBeInTheDocument();
  });

  it('ignores a delayed send after switching rooms and keeps the current draft', async () => {
    const otherRoom = { ...room, id: 43, topic: 'Another room' };
    let resolve!: (value: ChatMessage) => void;
    vi.mocked(api.chat.list).mockResolvedValue({ items: [room, otherRoom], total: 2 });
    vi.mocked(api.chat.get).mockImplementation(async id => id === 42 ? detail
      : { ...detail, room: otherRoom, messages: [message(20, 43)], last_message_id: 20 });
    vi.mocked(api.chat.postMessage).mockReturnValueOnce(new Promise(done => { resolve = done; }));
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });
    await screen.findByText(detail.messages[0].body);
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'For the old room' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    fireEvent.click(screen.getByRole('button', { name: /Another room/ }));
    await screen.findByText('Message 20');
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Current draft' } });

    await act(async () => { resolve(message(21)); });

    expect(screen.getByRole('heading', { name: 'Another room' })).toBeInTheDocument();
    expect(screen.queryByText('Message 21')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Message')).toHaveValue('Current draft');
  });

  it.each(['failed request', 'invalid cursor'] as const)('keeps the last read cursor after a %s', async failure => {
    vi.useFakeTimers();
    const read = vi.mocked(api.chat.get).mockResolvedValueOnce(detail);
    if (failure === 'failed request') read.mockRejectedValueOnce(new Error('Read failed'));
    else read.mockResolvedValueOnce({ ...detail, has_more: true });
    read.mockResolvedValueOnce({ ...detail, messages: [message(8)], last_message_id: 8 });
    await act(async () => { renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] }); });

    await act(async () => { await vi.advanceTimersByTimeAsync(4_000); });

    expect(api.chat.get).toHaveBeenNthCalledWith(2, 42, 7);
    expect(api.chat.get).toHaveBeenNthCalledWith(3, 42, 7);
    expect(screen.getByText('Message 8')).toBeInTheDocument();
    expect(screen.getByText(detail.messages[0].body)).toBeInTheDocument();
  });

  it('keeps reading position and the draft after a failed send', async () => {
    vi.mocked(api.chat.postMessage).mockRejectedValueOnce(new Error('Send failed'));
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] });
    await screen.findByText(detail.messages[0].body);
    const pane = screen.getByRole('region', { name: 'Chat messages' });
    Object.defineProperties(pane, {
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 300 },
    });
    pane.scrollTop = 100;
    fireEvent.scroll(pane);
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Keep this draft' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Send' })); });

    expect(api.chat.postMessage).toHaveBeenCalledWith(42, 'Keep this draft');
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled();
    expect(pane.scrollTop).toBe(100);
    expect(screen.getByRole('button', { name: 'Jump to latest' })).toBeInTheDocument();
    expect(screen.getByLabelText('Message')).toHaveValue('Keep this draft');
  });
});
