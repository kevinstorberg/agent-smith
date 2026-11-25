import type {
  ActionItemEpicGroup,
  ActionItemGroupedPage,
  ActionItemMove,
  ActionItemQueueMove,
  ActionItemRow,
  ActionItemTaskEntry,
  ActionItemTaskPage,
  ActionItemEpic,
  Paginated,
} from '../../api';
import { actionItem } from './actionItemFixture';

export function queuePage(
  page: Paginated<ActionItemRow>,
): ActionItemGroupedPage {
  return {
    items: page.items.map((item) => ({
      kind: 'item',
      item,
      entry_id: item.id,
      parent_epic_id: null,
      position: item.priority,
    })),
    total: page.total,
    matching_count: page.total,
  };
}

export function queueMove(
  id: number,
  move: ActionItemMove | { expected_revision: number; [key: string]: number },
): ActionItemQueueMove {
  const anchor = {
    kind: 'item' as const,
    id: (move.before_id ?? move.after_id)!,
    expected_revision: 1,
  };
  return {
    source: { kind: 'item', id, expected_revision: move.expected_revision },
    ...(move.before_id ? { before: anchor } : { after: anchor }),
  };
}

export function epicGroup(
  id = 10,
  children = [actionItem(2)],
): ActionItemEpicGroup {
  let openPosition = 0;
  return {
    kind: 'epic',
    epic: {
      id,
      title: 'Release',
      revision: 3,
      cohort: `cohort-${id}`,
      open_count: children.filter((item) => item.status === 'open').length,
      entry_id: id + 1000,
      position: 2,
      created_at: '2026-11-24T12:00:00Z',
      updated_at: '2026-11-24T12:00:00Z',
    },
    children: children.map((item) => ({
      kind: 'item',
      item,
      entry_id: item.id,
      parent_epic_id: id,
      position: item.status === 'open' ? ++openPosition : null,
    })),
    matching_count: children.length,
    total_count: children.length,
  };
}

export function taskEntry(
  item: ActionItemRow,
  {
    parent,
    rootIndex,
    position,
  }: {
    parent: ActionItemEpic | null;
    rootIndex: number;
    position: number | null;
  },
): ActionItemTaskEntry {
  return {
    kind: 'item',
    item,
    entry_id: item.id,
    parent_epic_id: parent?.id ?? null,
    parent,
    root_index: rootIndex,
    position,
  };
}

export function taskPage({
  items,
  total,
  root_total,
}: {
  items: ActionItemTaskEntry[];
  total: number;
  root_total: number;
}): ActionItemTaskPage {
  return { items, total, root_total, matching_count: total };
}
