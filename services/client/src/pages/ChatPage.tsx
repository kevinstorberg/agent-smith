import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { api, type ChatMessage, type ChatRoom, type ChatRoomDetail } from '../api';
import { ChatTranscript } from '../components/ChatTranscript';
import { CopyButton } from '../components/CopyButton';
import { useNotification } from '../context/useNotification';
import { usePolling } from '../hooks/usePolling';
import { usePagination } from '../hooks/usePagination';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { FilterBar } from '../components/FilterBar';
import { Pagination } from '../components/Pagination';
import { CHAT_SORT_OPTIONS, CHAT_STATUSES } from '../constants';
import { useViewPreferences } from '../hooks/useViewPreferences';
import { parseViewField } from '../utils/viewPreferences';

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
  const preferences = useViewPreferences('chat');
  const { q: search, status, sort } = preferences.values;
  const query = useDebouncedValue(search.trim());
  const list = usePagination<ChatRoom>((limit, offset) => api.chat.list({ limit, offset,
    q: query || undefined, status: status === 'all' ? undefined : status, sort }), [query, status, sort], 10, { ...preferences.pagination, enabled: query === search.trim() });
  const { items: rooms, setItems: setRooms, refresh } = list;
  const [selectedRoomId, setSelectedRoomId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ChatRoomDetail | null>(null);
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
  const latestRoomsRefresh = useRef(refresh);
  useEffect(() => { latestRoomsRefresh.current = refresh; }, [refresh]);
  const { notify } = useNotification();

  useEffect(() => {
    api.chat.config()
      .then(result => setAiParticipants(result.participants))
      .catch(error => notify(error instanceof Error ? error.message : String(error), 'error'));
  }, [notify]);

  useEffect(() => {
    if (!list.loading && !list.error) setSelectedRoomId(current => current ?? rooms[0]?.id ?? null);
  }, [list.loading, list.error, rooms]);

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
    await Promise.all([refresh({ showLoading: false }), loadSelectedRoom(false)]);
  }, { intervalMs: CHAT_POLL_INTERVAL_MS });

  async function createRoom(event: FormEvent) {
    event.preventDefault();
    if (!topic.trim()) return;
    setSaving(true);
    try {
      const room = await api.chat.create({ topic, context });
      setSelectedRoomId(room.id);
      setDetail({ room, messages: [], last_message_id: 0, has_more: false });
      setTopic('');
      setContext('');
      setShowCreate(false);
      await latestRoomsRefresh.current({ showLoading: false });
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
      await latestRoomsRefresh.current({ showLoading: false });
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
    const session = roomSession.current;
    setSaving(true);
    try {
      const room = await api.chat.update(detail.room.id, { topic: editTopic, context: editContext });
      if (roomSession.current !== session) return;
      setDetail(current => current?.room.id === room.id ? { ...current, room } : current);
      setEditing(false);
      await latestRoomsRefresh.current({ showLoading: false });
    } catch (error) {
      if (roomSession.current === session) notify(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setSaving(false);
    }
  }

  async function deleteRoom() {
    if (!detail) return;
    if (!confirm('Delete this room and its entire transcript? This cannot be undone.')) return;
    const session = roomSession.current;
    const roomId = detail.room.id;
    setSaving(true);
    try {
      await api.chat.remove(roomId);
      setRooms(current => current.filter(existing => existing.id !== roomId));
      if (roomSession.current === session) {
        setSelectedRoomId(rooms.find(existing => existing.id !== roomId)?.id ?? null);
        setDetail(null);
      }
      notify('Room deleted', 'success');
      await latestRoomsRefresh.current({ showLoading: false });
    } catch (error) {
      notify(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setSaving(false);
    }
  }

  async function stopAgentAccess() {
    if (!detail || detail.room.state === 'closed') return;
    if (!confirm('Stop agent access to this room? This cannot be undone.')) return;
    const session = roomSession.current;
    setSaving(true);
    try {
      const room = await api.chat.stop(detail.room.id);
      if (roomSession.current !== session) return;
      setDetail(current => current?.room.id === room.id ? { ...current, room } : current);
      notify('Agent access stopped', 'success');
      await latestRoomsRefresh.current({ showLoading: false });
    } catch (error) {
      if (roomSession.current === session) notify(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setSaving(false);
    }
  }

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

      <FilterBar nameValue={search} onNameChange={value => preferences.setField('q', value)} onReset={preferences.reset} nameLabel="Search rooms" namePlaceholder="Search topics or context...">
        <label><span className="form-label">Room status</span>
          <select className="input" value={status} onChange={event => preferences.setField('status', parseViewField('chat', 'status', event.target.value))}>
            {CHAT_STATUSES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label><span className="form-label">Sort rooms</span>
          <select className="input" value={sort} onChange={event => preferences.setField('sort', parseViewField('chat', 'sort', event.target.value))}>
            {CHAT_SORT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
      </FilterBar>

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
          {list.loading && <div className="loading">Loading rooms...</div>}
          {list.error && <div role="alert">Could not load rooms. <button className="btn" onClick={() => refresh()}>Retry</button></div>}
          {!list.loading && !list.error && rooms.map(room => (
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
          {!list.loading && !list.error && rooms.length === 0 && <div className="chat-empty">{query || status !== 'all' ? 'No rooms match these filters.' : 'No rooms yet.'}</div>}
          {!list.loading && !list.error && selectedRoomId !== null && !rooms.some(room => room.id === selectedRoomId)
            && <p className="text-muted-sm">The selected room is outside the current results.</p>}
          {!list.error && <Pagination total={list.total} limit={list.limit} offset={list.offset} disabled={list.loading}
            onPageChange={list.setOffset} onLimitChange={value => { list.setLimit(value); list.setOffset(0); }} />}
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
                  {detail.room.context && <p className="chat-room-context" role="region" aria-label="Room context" tabIndex={0}>{detail.room.context}</p>}
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
