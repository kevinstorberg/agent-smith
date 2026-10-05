import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, type ChatMessage, type ChatRoom, type ChatRoomDetail } from '../api';
import { CopyButton } from '../components/CopyButton';
import { useNotification } from '../context/useNotification';
import { useAssignableAgents } from '../hooks/useAssignableAgents';
import { usePolling } from '../hooks/usePolling';

const CHAT_POLL_INTERVAL_MS = 2_000;

function invitePrompt(roomId: number, agent: string): string {
  return `Join Agent Smith Chat Room ${roomId} as ${agent}. Use the chat MCP tools to collaborate in this room: call chat_read with room_id=${roomId}, after_message_id=0, and wait_seconds=20; reply with chat_post using agent="${agent}"; then keep reading with the returned last_message_id until the outcome is "closed".`;
}

function appendMessage(detail: ChatRoomDetail, message: ChatMessage): ChatRoomDetail {
  if (detail.messages.some(existing => existing.id === message.id)) return detail;
  return {
    ...detail,
    messages: [...detail.messages, message],
    last_message_id: message.id,
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
  const { agents: codingAgents } = useAssignableAgents();
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
    if (selectedRoomId === null) return;
    try {
      const result = await api.chat.get(selectedRoomId);
      setDetail(result);
    } catch (error) {
      if (showError) notify(error instanceof Error ? error.message : String(error), 'error');
    }
  }, [notify, selectedRoomId]);

  useEffect(() => {
    loadRooms();
  }, [loadRooms]);

  useEffect(() => {
    setDetail(null);
    setEditing(false);
    loadSelectedRoom();
  }, [loadSelectedRoom]);

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
    setSaving(true);
    try {
      const message = await api.chat.postMessage(detail.room.id, draft);
      setDetail(current => current ? appendMessage(current, message) : current);
      setDraft('');
      await loadRooms(false);
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error), 'error');
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
    <div>
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
                  <span>Invite an open session:</span>
                  {codingAgents.map(agent => (
                    <span key={agent} className="chat-invite">
                      {agent}
                      <CopyButton text={invitePrompt(detail.room.id, agent)} />
                    </span>
                  ))}
                </div>
              )}

              <div className="chat-transcript">
                {detail.messages.map(message => (
                  <article key={message.id} className={`chat-message chat-message-${message.author}`}>
                    <div className="chat-message-meta">
                      <strong>{message.author}</strong>
                      <time dateTime={message.created_at}>
                        {new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </time>
                    </div>
                    <div className="chat-message-body">{message.body}</div>
                  </article>
                ))}
                {detail.messages.length === 0 && (
                  <div className="chat-empty">No messages yet. Invite an agent or send the first message.</div>
                )}
                {detail.has_more && (
                  <div className="chat-empty">Showing the first 100 messages.</div>
                )}
              </div>

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
