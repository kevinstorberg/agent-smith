import type { ActionItemEpic, ActionItemEpicReference } from '../api';

export const epicReference = (
  epic: ActionItemEpic,
): ActionItemEpicReference => ({
  id: epic.id,
  expected_revision: epic.revision,
  cohort: epic.cohort,
});

export function epicOptionLabel(
  epic: Pick<ActionItemEpic, 'id' | 'title'>,
  epics: ActionItemEpic[],
) {
  return `${epic.title}${epics.some((other) => other.id !== epic.id && other.title === epic.title) ? ` #${epic.id}` : ''}`;
}
