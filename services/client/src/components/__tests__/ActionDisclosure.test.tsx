import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ActionDisclosure } from '../ActionDisclosure';

describe('ActionDisclosure', () => {
  it('keeps secondary actions mounted and closes on Escape with focus on the stable trigger', async () => {
    const user = userEvent.setup();
    const parentKey = vi.fn();
    render(
      <div onKeyDown={parentKey}>
        <ActionDisclosure label="More actions for First">
          <button>Edit First</button>
        </ActionDisclosure>
      </div>,
    );
    const action = screen.getByText('Edit First');
    const trigger = screen.getByRole('button', {
      name: 'More actions for First',
    });
    expect(action).not.toBeVisible();
    await user.click(trigger);
    await user.tab();
    expect(action).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveFocus();
    expect(action).not.toBeVisible();
    expect(action.isConnected).toBe(true);
    expect(parentKey).not.toHaveBeenCalled();
  });

  it('closes before a command so queue writes remember the stable trigger', async () => {
    const user = userEvent.setup();
    const command = vi.fn(() => {
      expect(
        screen.getByRole('button', { name: 'More actions for First' }),
      ).toHaveFocus();
    });
    render(
      <ActionDisclosure label="More actions for First">
        {(close) => (
          <button
            onClick={() => {
              close();
              command();
            }}
          >
            Move to top
          </button>
        )}
      </ActionDisclosure>,
    );
    await user.click(
      screen.getByRole('button', { name: 'More actions for First' }),
    );
    await user.click(screen.getByRole('button', { name: 'Move to top' }));
    expect(command).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole('group', { name: 'More actions for First' }),
    ).not.toBeInTheDocument();
  });

  it('closes on outside pointer interaction without taking focus from the selected control', async () => {
    const user = userEvent.setup();
    render(
      <>
        <ActionDisclosure label="Project options">
          <button>New project</button>
        </ActionDisclosure>
        <label>
          Search
          <input />
        </label>
      </>,
    );
    await user.click(screen.getByRole('button', { name: 'Project options' }));
    await user.tab();
    await user.click(screen.getByRole('textbox', { name: 'Search' }));
    expect(screen.getByRole('textbox', { name: 'Search' })).toHaveFocus();
    expect(
      screen.getByRole('button', { name: 'Project options' }),
    ).toHaveAttribute('aria-expanded', 'false');
  });

  it('preserves a nested draft while dismissal is suspended, even if the source revision changes', async () => {
    const user = userEvent.setup();
    function controls(locked: boolean, revision: number) {
      return (
        <>
          <ActionDisclosure
            label="More actions for First"
            disabled={locked}
            dismissible={!locked}
            resetKey={revision}
          >
            <label>
              Epic name
              <input />
            </label>
          </ActionDisclosure>
          <button>Outside</button>
        </>
      );
    }
    const { rerender } = render(controls(false, 1));
    await user.click(
      screen.getByRole('button', { name: 'More actions for First' }),
    );
    const input = screen.getByRole('textbox', { name: 'Epic name' });
    await user.type(input, 'Reviewed UUID receipt');
    rerender(controls(true, 2));
    await user.click(screen.getByRole('button', { name: 'Outside' }));
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(input).toBeVisible();
    expect(input).toHaveValue('Reviewed UUID receipt');
    rerender(controls(false, 2));
    expect(input).not.toBeVisible();
    expect(input).toHaveValue('Reviewed UUID receipt');
  });

  it('never steals focus when unopened disclosures refresh or become disabled', () => {
    const { rerender } = render(
      <ActionDisclosure label="More actions for First" resetKey={1}>
        <button>Edit First</button>
      </ActionDisclosure>,
    );
    expect(document.body).toHaveFocus();
    rerender(
      <ActionDisclosure label="More actions for First" resetKey={2} disabled>
        <button>Edit First</button>
      </ActionDisclosure>,
    );
    expect(document.body).toHaveFocus();
    rerender(
      <ActionDisclosure label="More actions for First" resetKey={3}>
        <button>Edit First</button>
      </ActionDisclosure>,
    );
    expect(document.body).toHaveFocus();
  });

  it('closes an open disclosure when its source changes, restoring the trigger only when focus was inside', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ActionDisclosure label="More actions for First" resetKey={1}>
        <button>Edit First</button>
      </ActionDisclosure>,
    );
    await user.click(
      screen.getByRole('button', { name: 'More actions for First' }),
    );
    await user.tab();
    rerender(
      <ActionDisclosure label="More actions for First" resetKey={2}>
        <button>Edit First</button>
      </ActionDisclosure>,
    );
    expect(
      screen.getByRole('button', { name: 'More actions for First' }),
    ).toHaveFocus();
    expect(screen.getByText('Edit First')).not.toBeVisible();
  });

  it('lets Tab leave the disclosure without trapping or redirecting focus', async () => {
    const user = userEvent.setup();
    render(
      <>
        <ActionDisclosure label="More actions for First">
          <button>Edit First</button>
        </ActionDisclosure>
        <button>Next row</button>
      </>,
    );
    await user.click(
      screen.getByRole('button', { name: 'More actions for First' }),
    );
    await user.tab();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Next row' })).toHaveFocus();
    expect(screen.getByText('Edit First')).not.toBeVisible();
  });
  it('exposes open state additively so transient content resets while existing callers remain mounted', async () => {
    const user = userEvent.setup();
    render(
      <ActionDisclosure label="Choose Epic">
        {(_close, open) => open && <input aria-label="Search choices" />}
      </ActionDisclosure>,
    );
    const trigger = screen.getByRole('button', { name: 'Choose Epic' });
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await user.click(trigger);
    await user.type(screen.getByRole('textbox'), 'temporary query');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await user.click(trigger);
    expect(screen.getByRole('textbox')).toHaveValue('');
  });
});
