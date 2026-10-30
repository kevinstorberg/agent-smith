import type { ActionItem } from '../../api';

export function actionItem(id: number, overrides: Partial<ActionItem> = {}): ActionItem {
  return {
    id, title: `Task ${id}`, description: `Description ${id}`, project: 'Work', tags: ['security'],
    status: 'open', completed_at: overrides.status === 'completed' ? '2026-10-30T13:00:00Z' : null, revision: 1,
    priority: overrides.status === 'completed' ? null : id,
    created_at: '2026-10-30T12:00:00Z', updated_at: '2026-10-30T12:00:00Z', ...overrides,
  };
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((accept, refuse) => { resolve = accept; reject = refuse; });
  return { promise, resolve, reject };
}
