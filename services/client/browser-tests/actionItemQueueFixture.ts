import type { ActionItemRow, Paginated } from '../src/api';
import { queuePage } from '../src/pages/__tests__/actionItemEpicFixture';
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
      return status >= 400 ? page : queuePage(page as Paginated<ActionItemRow>);
    },
    status,
  );
}
