import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, type ChatRoom, type ChatRoomDetail } from '../../api';
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
    },
  },
}));

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

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.chat.list).mockResolvedValue({ items: [room], total: 1 });
  vi.mocked(api.chat.get).mockResolvedValue(detail);
  vi.mocked(api.chat.config).mockResolvedValue({ participants: ['Kimi', 'Qwen'] });
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('ChatPage', () => {
  it('loads rooms and the selected transcript', async () => {
    renderWithProviders(<ChatPage />);

    expect(await screen.findByText('Choose a cache strategy')).toBeInTheDocument();
    expect(await screen.findByText('Extend the existing cache interface.')).toBeInTheDocument();
    expect(screen.getByText('Keep it small.')).toBeInTheDocument();
  });

  it('creates a room from topic and optional context', async () => {
    const created = { ...room, id: 43, topic: 'New topic' };
    vi.mocked(api.chat.create).mockResolvedValue(created);
    renderWithProviders(<ChatPage />);

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
    renderWithProviders(<ChatPage />);

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

  it('copies an invite naming the real agent and room', async () => {
    renderWithProviders(<ChatPage />);

    await screen.findByText('Extend the existing cache interface.');
    fireEvent.click(screen.getAllByText('Copy')[1]);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('Chat Room 42 as codex'),
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
    renderWithProviders(<ChatPage />);

    fireEvent.click(await screen.findByText('Stop Agent Access'));

    await waitFor(() => expect(api.chat.stop).toHaveBeenCalledWith(42));
    expect(await screen.findByText('Agent Access Stopped')).toBeDisabled();
    expect(screen.getByLabelText('Message')).toBeDisabled();
  });

  it('renders configured AI participant messages with their byline', async () => {
    vi.mocked(api.chat.get).mockResolvedValue({
      ...detail,
      messages: [
        ...detail.messages,
        {
          id: 9,
          room_id: 42,
          author: 'Kimi',
          body: 'I would benchmark both caches first.',
          created_at: '2026-09-09T12:04:00Z',
        },
      ],
      last_message_id: 9,
    });
    renderWithProviders(<ChatPage />);

    const body = await screen.findByText('I would benchmark both caches first.');
    expect(body.closest('article')).toHaveClass('chat-message-Kimi');
    expect(screen.getByText('Kimi')).toBeInTheDocument();
  });

  it('offers an AI mention hint but never an AI invite button', async () => {
    renderWithProviders(<ChatPage />);

    expect(
      await screen.findByText('Mention @Kimi or @Qwen to bring an AI into the room.'),
    ).toBeInTheDocument();
    const invites = screen.getByText('Invite an open session:').parentElement!;
    expect(invites).not.toHaveTextContent('Kimi');
    expect(invites).not.toHaveTextContent('Qwen');
  });

  it('polls without issuing overlapping state machinery', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProviders(<ChatPage />);
    await waitFor(() => expect(api.chat.get).toHaveBeenCalled());
    vi.mocked(api.chat.list).mockClear();
    vi.mocked(api.chat.get).mockClear();

    await act(async () => {
      vi.advanceTimersByTime(2_000);
      await Promise.resolve();
    });

    expect(api.chat.list).toHaveBeenCalledTimes(1);
    expect(api.chat.get).toHaveBeenCalledTimes(1);
  });
});
