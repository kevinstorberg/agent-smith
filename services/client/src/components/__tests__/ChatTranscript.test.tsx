import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChatMessage } from '../../api';
import { ChatTranscript } from '../ChatTranscript';

const message = (id: number): ChatMessage => ({
  id,
  room_id: 42,
  author: 'user',
  body: `Message ${id}`,
  created_at: '2026-11-02T20:00:00Z',
});

describe('ChatTranscript', () => {
  let height: number;
  let positions: WeakMap<Element, number>;
  let writes: number[];

  beforeEach(() => {
    height = 1000;
    positions = new WeakMap();
    writes = [];
    vi.spyOn(Element.prototype, 'scrollHeight', 'get').mockImplementation(() => height);
    vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(300);
    vi.spyOn(Element.prototype, 'scrollTop', 'get').mockImplementation(function (this: Element) {
      return positions.get(this) ?? 0;
    });
    vi.spyOn(Element.prototype, 'scrollTop', 'set').mockImplementation(function (this: Element, value: number) {
      writes.push(value);
      positions.set(this, Math.min(value, Math.max(0, height - 300)));
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  const pane = () => screen.getByRole('region', { name: 'Chat messages' });
  const scrollTo = (top: number) => {
    positions.set(pane(), top);
    fireEvent.scroll(pane());
  };

  it('starts at the bottom and preserves message content and loading status', () => {
    render(<ChatTranscript messages={[message(1)]} hasMore sentMessageId={null} />);

    expect(pane().scrollTop).toBe(700);
    expect(writes).toEqual([1000]);
    expect(pane()).toHaveAttribute('tabindex', '0');
    expect(screen.getByText('user')).toBeInTheDocument();
    expect(screen.getByText('Message 1')).toBeInTheDocument();
    expect(pane().querySelector('time')).toHaveAttribute('datetime', message(1).created_at);
    expect(screen.getByText('Loading more messages...')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Jump to latest' })).not.toBeInTheDocument();
  });

  it('follows appended messages while at the bottom', () => {
    const view = render(<ChatTranscript messages={[message(1)]} hasMore={false} sentMessageId={null} />);
    writes.length = 0;
    height = 1200;

    view.rerender(<ChatTranscript messages={[message(1), message(2)]} hasMore={false} sentMessageId={null} />);

    expect(writes).toEqual([1200]);
    expect(pane().scrollTop).toBe(900);
  });

  it('preserves reading position on appends and never scrolls for an unchanged poll', () => {
    const view = render(<ChatTranscript messages={[message(1)]} hasMore={false} sentMessageId={null} />);
    writes.length = 0;
    view.rerender(<ChatTranscript messages={[{ ...message(1) }]} hasMore sentMessageId={null} />);
    expect(writes).toEqual([]);

    scrollTo(100);
    height = 1200;
    view.rerender(<ChatTranscript messages={[message(1), message(2)]} hasMore={false} sentMessageId={null} />);
    view.rerender(<ChatTranscript messages={[{ ...message(1) }, { ...message(2) }]} hasMore sentMessageId={null} />);

    expect(writes).toEqual([]);
    expect(pane().scrollTop).toBe(100);
    expect(screen.getByRole('button', { name: 'Jump to latest' })).toBeInTheDocument();
  });

  it('jumps to the latest message, focuses the pane, and resumes following', () => {
    const view = render(<ChatTranscript messages={[message(1)]} hasMore={false} sentMessageId={null} />);
    scrollTo(100);
    writes.length = 0;
    const focus = vi.spyOn(pane(), 'focus');

    fireEvent.click(screen.getByRole('button', { name: 'Jump to latest' }));

    expect(writes).toEqual([1000]);
    expect(pane().scrollTop).toBe(700);
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(pane()).toHaveFocus();
    expect(screen.queryByRole('button', { name: 'Jump to latest' })).not.toBeInTheDocument();

    height = 1200;
    view.rerender(<ChatTranscript messages={[message(1), message(2)]} hasMore={false} sentMessageId={null} />);
    expect(pane().scrollTop).toBe(900);
  });

  it('forces one scroll for an own-send token and then allows reading older messages', () => {
    const view = render(<ChatTranscript messages={[message(1)]} hasMore={false} sentMessageId={null} />);
    scrollTo(100);
    writes.length = 0;
    height = 1200;

    view.rerender(<ChatTranscript messages={[message(1), message(2)]} hasMore={false} sentMessageId={2} />);

    expect(writes).toEqual([1200]);
    expect(pane().scrollTop).toBe(900);
    expect(screen.queryByRole('button', { name: 'Jump to latest' })).not.toBeInTheDocument();
    scrollTo(100);
    writes.length = 0;
    view.rerender(<ChatTranscript messages={[message(1), message(2)]} hasMore sentMessageId={2} />);
    height = 1400;
    view.rerender(<ChatTranscript messages={[message(1), message(2), message(3)]} hasMore={false} sentMessageId={2} />);

    expect(writes).toEqual([]);
    expect(pane().scrollTop).toBe(100);
    expect(screen.getByRole('button', { name: 'Jump to latest' })).toBeInTheDocument();
  });

  it('resumes following when the reader scrolls within 80 pixels of the bottom', () => {
    const view = render(<ChatTranscript messages={[message(1)]} hasMore={false} sentMessageId={null} />);
    scrollTo(100);
    writes.length = 0;

    scrollTo(620);

    expect(writes).toEqual([]);
    expect(screen.queryByRole('button', { name: 'Jump to latest' })).not.toBeInTheDocument();
    height = 1200;
    view.rerender(<ChatTranscript messages={[message(1), message(2)]} hasMore={false} sentMessageId={null} />);

    expect(writes).toEqual([1200]);
    expect(pane().scrollTop).toBe(900);
  });
});
