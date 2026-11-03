import type { ChatMessage, ChatRoom, ChatRoomDetail } from '../src/api';

const stamp = '2026-11-03T12:00:00Z';
export function chatRoom(overrides: Partial<ChatRoom> = {}): ChatRoom {
  return { id: 1, topic: 'Review release ownership', context: 'Keep the decision and next steps clear.', state: 'open',
    created_at: stamp, updated_at: stamp, closed_at: null, ...overrides };
}

export function chatMessage(id: number, overrides: Partial<ChatMessage> = {}): ChatMessage {
  return { id, room_id: 1, author: id % 2 ? 'codex' : 'user',
    body: `Message ${id}: Review the release ownership and security decisions. ${'Include clear next steps and supporting context. '.repeat(5)}`,
    created_at: stamp, ...overrides };
}

export function chatDetail(room: ChatRoom, messages: ChatMessage[], cursor = 0): ChatRoomDetail {
  return { room, messages: messages.filter(message => message.id > cursor),
    last_message_id: messages.at(-1)?.id ?? cursor, has_more: false };
}
