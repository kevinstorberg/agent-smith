import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useActionItemQueue } from '../../hooks/useActionItemQueue';
import { renderWithProviders } from '../../test-utils';
import { actionItem } from '../../pages/__tests__/actionItemFixture';
import { ActionItemQueueTable } from '../ActionItemQueueTable';

describe('queue row deletion capability', () => {
  it.each([true, false])(
    'keeps Delete absent without explicit opt-in even when source.remove exists: %s',
    async (hasRemove) => {
      const remove = vi.fn().mockResolvedValue({ deleted: true, id: 1 });
      const source = {
        list: vi.fn().mockResolvedValue({ items: [actionItem(1)], total: 1 }),
        get: vi.fn().mockResolvedValue(actionItem(1)),
        update: vi.fn().mockResolvedValue(actionItem(1)),
        move: vi.fn().mockResolvedValue(actionItem(1)),
        ...(hasRemove ? { remove } : {}),
      };
      function Consumer() {
        const queue = useActionItemQueue({
          source,
          filters: {},
          criteria: 'same',
          viewKey: 'same',
          reorderableView: false,
        });
        return (
          <ActionItemQueueTable
            queue={queue}
            status="open"
            onEdit={() => undefined}
          />
        );
      }
      renderWithProviders(<Consumer />);
      await screen.findByRole('button', { name: 'Task 1' });
      expect(
        screen.queryByRole('button', { name: 'Delete Task 1' }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Complete Task 1' }),
      ).toBeEnabled();
      expect(screen.getByRole('button', { name: 'Edit Task 1' })).toBeEnabled();
      expect(remove).not.toHaveBeenCalled();
    },
  );
});
