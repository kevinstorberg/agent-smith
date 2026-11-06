import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ActionItemQueueTable } from '../ActionItemQueueTable';
import { useActionItemQueue } from '../../hooks/useActionItemQueue';
import type { ActionItemQueueSource } from '../../hooks/useActionItemQueue';
import { actionItem } from '../../pages/__tests__/actionItemFixture';
import { renderWithProviders } from '../../test-utils';

const items = [
  actionItem(1, {
    due_at: '2026-12-01T14:15:00Z',
    updated_at: '2020-02-03T12:00:00Z',
  }),
  actionItem(2, { due_at: null }),
  actionItem(3),
];
const source: ActionItemQueueSource = {
  list: vi.fn(async () => ({ items, total: items.length })),
  get: vi.fn(async (id: number) => actionItem(id)),
  update: vi.fn(async () => {
    throw new Error('Date presentation must not update records');
  }),
  move: vi.fn(async () => {
    throw new Error('Date presentation must not reorder records');
  }),
};

function DateTable({ showDueDate }: { showDueDate?: boolean }) {
  const queue = useActionItemQueue({
    source,
    filters: {},
    criteria: 'date-column',
    viewKey: 'date-column',
    reorderableView: false,
  });
  return (
    <ActionItemQueueTable
      queue={queue}
      sort="manual"
      onSort={() => undefined}
      onEdit={() => undefined}
      showDueDate={showDueDate}
      status="open"
    />
  );
}

beforeEach(() => vi.clearAllMocks());

describe('Action Item queue date columns', () => {
  it('uses the due column only when opted in and gives missing deadlines a placeholder', async () => {
    renderWithProviders(<DateTable showDueDate />);
    await screen.findByRole('button', { name: 'Task 1' });
    expect(
      screen.getByRole('columnheader', { name: 'Due date' }),
    ).toBeVisible();
    expect(screen.queryByRole('columnheader', { name: 'Updated' })).toBeNull();
    const rows = screen.getAllByRole('row').slice(1);
    const first = within(rows[0]).getAllByRole('cell');
    expect(first[3]).toHaveTextContent('2026');
    expect(first[3]).not.toHaveTextContent('Feb');
    expect(first[1]).not.toHaveTextContent('Due');
    for (const row of rows.slice(1))
      expect(within(row).getAllByRole('cell')[3]).toHaveTextContent(
        'No due date',
      );
    expect(source.update).not.toHaveBeenCalled();
    expect(source.move).not.toHaveBeenCalled();
  });

  it('retains the Updated column for default shared queues even when a row has a deadline', async () => {
    renderWithProviders(<DateTable />);
    await screen.findByRole('button', { name: 'Task 1' });
    expect(screen.getByRole('columnheader', { name: 'Updated' })).toBeVisible();
    expect(screen.queryByRole('columnheader', { name: 'Due date' })).toBeNull();
    const row = screen.getAllByRole('row')[1];
    expect(within(row).getAllByRole('cell')[3]).toHaveTextContent('Feb');
    expect(within(row).getAllByRole('cell')[1]).not.toHaveTextContent('Due');
    expect(source.update).not.toHaveBeenCalled();
    expect(source.move).not.toHaveBeenCalled();
  });
});
