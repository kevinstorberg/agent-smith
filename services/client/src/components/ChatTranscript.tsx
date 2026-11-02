import { useLayoutEffect, useRef, useState } from 'react';
import type { ChatMessage } from '../api';

interface ChatTranscriptProps {
  messages: ChatMessage[];
  hasMore: boolean;
  sentMessageId: number | null;
}

export function ChatTranscript({ messages, hasMore, sentMessageId }: ChatTranscriptProps) {
  const transcript = useRef<HTMLDivElement>(null);
  const handledSend = useRef<number | null>(null);
  const displayed = useRef<{ lastId: number | undefined; count: number } | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const lastMessageId = messages.at(-1)?.id;

  useLayoutEffect(() => {
    const element = transcript.current;
    const changed = displayed.current === null
      || displayed.current.lastId !== lastMessageId || displayed.current.count !== messages.length;
    displayed.current = { lastId: lastMessageId, count: messages.length };
    const sent = sentMessageId !== null && sentMessageId !== handledSend.current;
    if (sent) handledSend.current = sentMessageId;
    if (element && ((changed && atBottom) || sent)) {
      element.scrollTop = element.scrollHeight;
      if (sent) setAtBottom(true);
    }
  }, [lastMessageId, messages.length, sentMessageId, atBottom]);

  function jumpToLatest() {
    const element = transcript.current;
    if (!element) return;
    element.scrollTop = element.scrollHeight;
    setAtBottom(true);
    element.focus({ preventScroll: true });
  }

  return (
    <div className="chat-transcript-area">
      <div
        className="chat-transcript"
        role="region"
        aria-label="Chat messages"
        tabIndex={0}
        ref={transcript}
        onScroll={event => {
          const element = event.currentTarget;
          setAtBottom(element.scrollHeight - element.scrollTop - element.clientHeight <= 80);
        }}
      >
        {messages.map(message => (
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
        {messages.length === 0 && (
          <div className="chat-empty">No messages yet. Invite an agent or send the first message.</div>
        )}
        {hasMore && <div className="chat-empty">Loading more messages...</div>}
      </div>
      {!atBottom && (
        <button type="button" className="btn chat-jump" onClick={jumpToLatest}>
          Jump to latest
        </button>
      )}
    </div>
  );
}
