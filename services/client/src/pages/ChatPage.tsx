import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { api, type ChatMessage, type ChatRoom, type ChatRoomDetail } from '../api';
import { ChatTranscript } from '../components/ChatTranscript';
import { CopyButton } from '../components/CopyButton';
import { useNotification } from '../context/useNotification';
import { usePolling } from '../hooks/usePolling';

const CHAT_POLL_INTERVAL_MS = 2_000;

interface RoomSession {
  roomId: number;
  cursor: number;
  inFlight: boolean;
}

function invitePrompt(roomId: number): string {
  return `Join Agent Smith chat room ${roomId} using the chat MCP tools. Collaborate until the room closes.`;
}

function mergeMessages(detail: ChatRoomDetail, incoming: ChatMessage[]): ChatRoomDetail {
  const byId = new Map(detail.messages.map(message => [message.id, message]));
  for (const message of incoming) byId.set(message.id, message);
  const messages = [...byId.values()].sort((left, right) => left.id - right.id);
  return {
    ...detail,
    messages,
    last_message_id: messages.at(-1)?.id ?? detail.last_message_id,
  };
}

export function ChatPage() {
  const [rooms, setRooms] = useState<ChatRoom[]>([]);
  const [selectedRoomId, setSelectedRoomId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ChatRoomDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [topic, setTopic] = useState('');
  const [context, setContext] = useState('');
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [aiParticipants, setAiParticipants] = useState<string[]>([]);
  const [editing, setEditing] = useState(false);
  const [editTopic, setEditTopic] = useState('');
  const [editContext, setEditContext] = useState('');
  const [lastSent, setLastSent] = useState<{ roomId: number; messageId: number } | null>(null);
  const roomSession = useRef<RoomSession | null>(null);
  const { notify } = useNotification();

  useEffect(() => {
    api.chat.config()
      .then(result => setAiParticipants(result.participants))
      .catch(error => notify(error instanceof Error ? error.message : String(error), 'error'));
  }, [notify]);

  const loadRooms = useCallback(async (showError = true) => {
    try {
      const result = await api.chat.list();
      setRooms(result.items);
      setSelectedRoomId(current => current ?? result.items[0]?.id ?? null);
    } catch (error) {
      if (showError) notify(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setLoading(false);
    }
  }, [notify]);

  const loadSelectedRoom = useCallback(async (showError = true) => {
    const session = roomSession.current;
    if (!session || session.roomId !== selectedRoomId || session.inFlight) return;
    session.inFlight = true;
    try {
      const result = await api.chat.get(session.roomId, session.cursor);
      if (roomSession.current !== session) return;
      if (result.room.id !== session.roomId || !Number.isSafeInteger(result.last_message_id)
          || result.last_message_id < session.cursor
          || (result.has_more && result.last_message_id === session.cursor)) {
        throw new Error('Chat returned an invalid message cursor. Refresh the room to try again.');
      }
      session.cursor = result.last_message_id;
      setDetail(current => mergeMessages(result, current?.room.id === session.roomId ? current.messages : []));
    } catch (error) {
      if (roomSession.current === session && showError) {
        notify(error instanceof Error ? error.message : String(error), 'error');
      }
    } finally {
      session.inFlight = false;
    }
  }, [notify, selectedRoomId]);

  useEffect(() => {
    loadRooms();
  }, [loadRooms]);

  useEffect(() => {
    const session = selectedRoomId === null ? null : { roomId: selectedRoomId, cursor: 0, inFlight: false };
    roomSession.current = session;
    setDetail(null);
    setEditing(false);
    loadSelectedRoom();
    return () => {
      if (roomSession.current === session) roomSession.current = null;
    };
  }, [loadSelectedRoom, selectedRoomId]);

  usePolling(async () => {
    await Promise.all([loadRooms(false), loadSelectedRoom(false)]);
  }, { intervalMs: CHAT_POLL_INTERVAL_MS });

  async function createRoom(event: FormEvent) {
    event.preventDefault();
    if (!topic.trim()) return;
    setSaving(true);
    try {
      const room = await api.chat.create({ topic, context });
      setRooms(current => [room, ...current.filter(existing => existing.id !== room.id)]);
      setSelectedRoomId(room.id);
      setDetail({ room, messages: [], last_message_id: 0, has_more: false });
      setTopic('');
      setContext('');
      setShowCreate(false);
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setSaving(false);
    }
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    if (!detail || detail.room.state === 'closed' || !draft.trim()) return;
    const session = roomSession.current;
    const roomId = detail.room.id;
    setSaving(true);
    try {
      const message = await api.chat.postMessage(roomId, draft);
      if (roomSession.current !== session) return;
      setDetail(current => current?.room.id === roomId ? mergeMessages(current, [message]) : current);
      setLastSent({ roomId, messageId: message.id });
      setDraft('');
      await loadRooms(false);
    } catch (error) {
      if (roomSession.current === session) notify(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setSaving(false);
    }
  }

  function startRoomEdit() {
    if (!detail) return;
    setEditTopic(detail.room.topic);
    setEditContext(detail.room.context);
    setEditing(true);
  }

  async function saveRoomEdit(event: FormEvent) {
    event.preventDefault();
    if (!detail || !editTopic.trim()) return;
    setSaving(true);
    try {
      const room = await api.chat.update(detail.room.id, { topic: editTopic, context: editContext });
      setDetail(current => current ? { ...current, room } : current);
      setRooms(current => current.map(existing => existing.id === room.id ? room : existing));
      setEditing(false);
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setSaving(false);
    }
  }

  async function deleteRoom() {
    if (!detail) return;
    if (!confirm('Delete this room and its entire transcript? This cannot be undone.')) return;
    setSaving(true);
    try {
      await api.chat.remove(detail.room.id);
      const remaining = rooms.filter(existing => existing.id !== detail.room.id);
      setRooms(remaining);
      setSelectedRoomId(remaining[0]?.id ?? null);
      setDetail(null);
      notify('Room deleted', 'success');
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setSaving(false);
    }
  }

  async function stopAgentAccess() {
    if (!detail || detail.room.state === 'closed') return;
    if (!confirm('Stop agent access to this room? This cannot be undone.')) return;
    setSaving(true);
    try {
      const room = await api.chat.stop(detail.room.id);
      setDetail(current => current ? { ...current, room } : current);
      setRooms(current => current.map(existing => existing.id === room.id ? room : existing));
      notify('Agent access stopped', 'success');
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div className="chat-page">
      <div className="page-header">
        <div>
          <h2 className="page-title">Chat Rooms</h2>
          <div className="chat-subtitle">A shared transcript for you and your open coding agents.</div>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(current => !current)}>
          {showCreate ? 'Cancel' : '+ New Room'}
        </button>
      </div>

      {showCreate && (
        <form className="card chat-create" onSubmit={createRoom}>
          <label className="form-label" htmlFor="chat-topic">Topic</label>
          <input
            id="chat-topic"
            className="input"
            maxLength={200}
            value={topic}
            onChange={event => setTopic(event.target.value)}
            placeholder="What should the group solve?"
            autoFocus
          />
          <label className="form-label" htmlFor="chat-context">Context (optional)</label>
          <textarea
            id="chat-context"
            className="input chat-context-input"
            maxLength={20_000}
            value={context}
            onChange={event => setContext(event.target.value)}
            placeholder="Constraints, relevant files, or desired outcome"
          />
          <button className="btn btn-primary" disabled={saving || !topic.trim()}>
            {saving ? 'Creating...' : 'Create Room'}
          </button>
        </form>
      )}

      <div className="chat-layout">
        <aside className="chat-room-list" aria-label="Chat rooms">
          {rooms.map(room => (
            <button
              key={room.id}
              className={`chat-room-button${selectedRoomId === room.id ? ' active' : ''}`}
              onClick={() => setSelectedRoomId(room.id)}
            >
              <span>{room.topic}</span>
              <span className={`tag ${room.state === 'open' ? 'tag-success' : 'tag-danger'}`}>
                {room.state}
              </span>
            </button>
          ))}
          {rooms.length === 0 && <div className="chat-empty">No rooms yet.</div>}
        </aside>

        <section className="chat-room" aria-live="polite">
          {!detail && selectedRoomId !== null && <div className="loading">Loading room...</div>}
          {!detail && selectedRoomId === null && (
            <div className="chat-empty">Create a room to start a group conversation.</div>
          )}
          {detail && (
            <>
              <header className="chat-room-header">
                <div>
                  <h3>{detail.room.topic}</h3>
                  {detail.room.context && <p>{detail.room.context}</p>}
                </div>
                <div className="chat-room-actions">
                  <button className="btn" disabled={saving} onClick={startRoomEdit}>
                    Edit
                  </button>
                  <button className="btn btn-danger" disabled={saving} onClick={deleteRoom}>
                    Delete
                  </button>
                  <button
                    className="btn btn-danger"
                    disabled={saving || detail.room.state === 'closed'}
                    onClick={stopAgentAccess}
                  >
                    {detail.room.state === 'closed' ? 'Agent Access Stopped' : 'Stop Agent Access'}
                  </button>
                </div>
              </header>

              {editing && (
                <form className="card chat-create" onSubmit={saveRoomEdit}>
                  <label className="form-label" htmlFor="chat-edit-topic">Topic</label>
                  <input
                    id="chat-edit-topic"
                    className="input"
                    maxLength={200}
                    value={editTopic}
                    onChange={event => setEditTopic(event.target.value)}
                    autoFocus
                  />
                  <label className="form-label" htmlFor="chat-edit-context">Context (optional)</label>
                  <textarea
                    id="chat-edit-context"
                    className="input chat-context-input"
                    maxLength={20_000}
                    value={editContext}
                    onChange={event => setEditContext(event.target.value)}
                  />
                  <div className="chat-room-actions">
                    <button className="btn btn-primary" disabled={saving || !editTopic.trim()}>
                      {saving ? 'Saving...' : 'Save'}
                    </button>
                    <button type="button" className="btn" disabled={saving} onClick={() => setEditing(false)}>
                      Cancel
                    </button>
                  </div>
                </form>
              )}

              {detail.room.state === 'open' && (
                <div className="chat-invites">
                  <span className="chat-invite">
                    Invite an agent:
                    <CopyButton text={invitePrompt(detail.room.id)} />
                  </span>
                </div>
              )}

              <ChatTranscript
                key={detail.room.id}
                messages={detail.messages}
                hasMore={detail.has_more}
                sentMessageId={lastSent?.roomId === detail.room.id ? lastSent.messageId : null}
              />

              {detail.room.state === 'open' && aiParticipants.length > 0 && (
                <div className="chat-empty">
                  Mention {aiParticipants.map(name => `@${name}`).join(' or ')} to bring an AI into the room.
                </div>
              )}
              <form className="chat-composer" onSubmit={sendMessage}>
                <textarea
                  className="input"
                  aria-label="Message"
                  maxLength={8_000}
                  value={draft}
                  onChange={event => setDraft(event.target.value)}
                  placeholder={detail.room.state === 'closed' ? 'This room is closed' : 'Message the room as User'}
                  disabled={saving || detail.room.state === 'closed'}
                />
                <button
                  className="btn btn-primary"
                  disabled={saving || detail.room.state === 'closed' || !draft.trim()}
                >
                  Send
                </button>
              </form>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
