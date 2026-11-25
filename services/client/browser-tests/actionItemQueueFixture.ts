import type { ActionItemRow, Paginated } from '../src/api';
import {
  queuePage,
  taskEntry,
  taskPage,
} from '../src/pages/__tests__/actionItemEpicFixture';
import type { APIRequest } from './fixtures';

export function flatQueueFixture(
  fixtureAPI: { get(path: string, response: unknown, status?: number): void },
  response: unknown,
  status = 200,
) {
  fixtureAPI.get(
    '/api/action-items/queue',
    async (request: APIRequest) => {
      const page =
        typeof response === 'function' ? await response(request) : response;
      if (status >= 400) return page;
      const rows = page as Paginated<ActionItemRow>;
      if (request.url.searchParams.get('kind') === 'task') {
        const offset = Number(request.url.searchParams.get('offset') || 0);
        return taskPage({
          items: rows.items.map((item, index) =>
            taskEntry(item, {
              parent: null,
              rootIndex: offset + index,
              position:
                request.url.searchParams.get('status') === 'open'
                  ? item.priority
                  : null,
            }),
          ),
          total: rows.total,
          root_total: rows.total,
        });
      }
      return queuePage(rows);
    },
    status,
  );
}
