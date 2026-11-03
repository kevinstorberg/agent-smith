import type { KeyboardEvent } from 'react';

function isOwnActivation(event: KeyboardEvent, keys: readonly string[]): boolean {
  return !event.defaultPrevented && event.target === event.currentTarget && keys.includes(event.key);
}

/**
 * Makes a non-button element keyboard accessible.
 * Returns props that should be spread onto the element.
 *
 * @example
 * <div {...makeKeyboardClickable(() => handleClick())} style={{ cursor: 'pointer' }}>
 *   Click me
 * </div>
 */
export function makeKeyboardClickable(onClick: () => void) {
  return {
    role: 'button' as const,
    tabIndex: 0,
    onClick,
    onKeyDown: (e: KeyboardEvent) => {
      if (isOwnActivation(e, ['Enter', ' '])) {
        e.preventDefault();
        onClick();
      }
    },
  };
}

/**
 * Makes a table row keyboard accessible for navigation.
 * Returns props that should be spread onto the <tr> element.
 *
 * @example
 * <tr {...makeRowClickable(() => navigate(`/item/${id}`))} style={{ cursor: 'pointer' }}>
 *   <td>Content</td>
 * </tr>
 */
export function makeRowClickable(onClick: () => void) {
  return {
    tabIndex: 0,
    onClick,
    onKeyDown: (e: KeyboardEvent) => {
      if (isOwnActivation(e, ['Enter'])) {
        e.preventDefault();
        onClick();
      }
    },
  };
}
