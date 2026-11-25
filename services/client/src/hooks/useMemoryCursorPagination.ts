import { useCallback, useState } from 'react';
import type { MemoryCursorPage } from '../api';
import { useApiRead } from './useApiRead';

interface Selection {
  key: string;
  generation: number;
  cursors: (string | null)[];
  index: number;
}

export function useMemoryCursorPagination(
  fetchPage: (
    limit: number,
    cursor: string | null,
  ) => Promise<MemoryCursorPage>,
  {
    enabled,
    limit,
    source,
  }: { enabled: boolean; limit: number; source: string },
) {
  const key = JSON.stringify([source, limit, enabled]);
  const firstPage = (generation: number): Selection => ({
    key,
    generation,
    cursors: [null],
    index: 0,
  });
  const [saved, setSelection] = useState(() => firstPage(0));
  let selection = saved;
  if (saved.key !== key) {
    selection = firstPage(saved.generation + 1);
    setSelection(selection);
  }
  const read = useCallback(
    async () => ({
      page: await fetchPage(limit, selection.cursors[selection.index]),
      selection,
    }),
    [fetchPage, limit, selection],
  );
  const request = useApiRead(read, { enabled });
  const accepted =
    request.data?.selection.key === key &&
    request.data.selection.generation === selection.generation
      ? request.data
      : null;
  const current = accepted?.selection;
  const loading = request.loading || (enabled && !accepted && !request.error);
  const busy = !enabled || loading;

  const next = () => {
    if (busy || !accepted?.page.next_cursor) return;
    setSelection({
      ...accepted.selection,
      cursors: [
        ...accepted.selection.cursors.slice(0, accepted.selection.index + 1),
        accepted.page.next_cursor,
      ],
      index: accepted.selection.index + 1,
    });
  };
  const previous = () => {
    if (busy || !current || current.index === 0) return;
    setSelection({ ...current, index: current.index - 1 });
  };
  const refresh = async () => {
    if (busy) return;
    if (current && current !== selection) setSelection(current);
    else await request.refresh();
  };
  const restart = async () => {
    if (busy) return;
    if (selection.index === 0) await request.refresh();
    else setSelection(firstPage(selection.generation + 1));
  };

  return {
    items: accepted?.page.items ?? [],
    loading,
    error: request.error,
    page: (current?.index ?? 0) + 1,
    hasPrevious: (current?.index ?? 0) > 0,
    hasNext: Boolean(accepted?.page.next_cursor),
    next,
    previous,
    refresh,
    retry: request.refresh,
    restart,
  };
}
