import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { makeKeyboardClickable, makeRowClickable } from '../a11y';

const helpers = [
  { name: 'keyboard clickable element', make: makeKeyboardClickable, keys: ['Enter', ' '] },
  { name: 'table row', make: makeRowClickable, keys: ['Enter'] },
];

describe.each(helpers)('$name activation', ({ make, keys }) => {
  function renderTarget(callback: () => void, preventDefault = false) {
    const target = <div data-testid="target" {...make(callback)} onKeyDownCapture={event => {
      if (preventDefault) event.preventDefault();
    }}>
      <button>Child action</button>
      <div role="button" tabIndex={0}>Drag handle</div>
    </div>;
    render(target);
    return screen.getByTestId('target');
  }

  it('activates supported keys originating on the target', () => {
    const callback = vi.fn();
    const target = renderTarget(callback);
    for (const key of keys) fireEvent.keyDown(target, { key });
    expect(callback).toHaveBeenCalledTimes(keys.length);
  });

  it('leaves descendant button and drag-handle keys to their controls', () => {
    const callback = vi.fn();
    renderTarget(callback);
    for (const name of ['Child action', 'Drag handle']) {
      for (const key of ['Enter', ' ']) fireEvent.keyDown(screen.getByRole('button', { name }), { key });
    }
    expect(callback).not.toHaveBeenCalled();
  });

  it('respects keys already consumed by another handler', () => {
    const callback = vi.fn();
    const target = renderTarget(callback, true);
    for (const key of keys) fireEvent.keyDown(target, { key });
    expect(callback).not.toHaveBeenCalled();
  });

  it('ignores unrelated keys', () => {
    const callback = vi.fn();
    fireEvent.keyDown(renderTarget(callback), { key: 'ArrowDown' });
    expect(callback).not.toHaveBeenCalled();
  });
});
