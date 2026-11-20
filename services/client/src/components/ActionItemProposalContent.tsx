import type { ActionItem, ActionItemProposal } from '../api';
import { DateCell } from './table';
import { ScrollableTable } from './ScrollableTable';
import './actionItemProposalContent.css';

const FIELDS = [
  ['title', 'Title'],
  ['description', 'Description'],
  ['project', 'Project'],
  ['tags', 'Tags'],
  ['status', 'Status'],
  ['due_at', 'Deadline'],
] as const;

type TaskField = (typeof FIELDS)[number][0];

function valueOf(
  item: Partial<ActionItem> | null | undefined,
  field: TaskField,
) {
  const value = item?.[field];
  if (field === 'tags') return (value as string[] | undefined) ?? [];
  return value ?? '';
}

function TaskValue({
  item,
  field,
}: {
  item: Partial<ActionItem> | null | undefined;
  field: TaskField;
}) {
  const value = valueOf(item, field);
  if (field === 'due_at' && typeof value === 'string' && value) {
    return <DateCell date={value} format="long" />;
  }
  return (
    <span style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
      {Array.isArray(value) ? value.join(', ') || 'None' : value || 'None'}
    </span>
  );
}

export function ActionItemProposalContent({
  proposal,
  targetStale,
  compact = false,
}: {
  proposal: ActionItemProposal;
  targetStale: boolean;
  compact?: boolean;
}) {
  const isUpdate = proposal.action === 'update';
  const before = proposal.before_snapshot ?? proposal.current_target;
  const after = proposal.proposed_item;
  const fields = FIELDS.filter(([field]) => {
    const value = valueOf(after, field);
    if (isUpdate)
      return JSON.stringify(valueOf(before, field)) !== JSON.stringify(value);
    if (!compact || field === 'title') return true;
    if (field === 'status' && value === 'open') return false;
    return Array.isArray(value) ? value.length > 0 : value !== '';
  });

  return (
    <>
      <ScrollableTable
        className="action-item-proposal-table"
        label={
          isUpdate ? 'Proposed action item changes' : 'Proposed action item'
        }
      >
        <thead>
          <tr>
            <th>Field</th>
            {isUpdate && <th>Before</th>}
            <th>Proposed</th>
          </tr>
        </thead>
        <tbody role="rowgroup">
          {fields.map(([field, label]) => (
            <tr key={field} role="row">
              <th scope="row" role="rowheader">
                {label}
              </th>
              {isUpdate && (
                <td role="cell" data-label="Before">
                  <TaskValue item={before} field={field} />
                </td>
              )}
              <td role="cell" data-label="Proposed">
                <TaskValue item={after} field={field} />
              </td>
            </tr>
          ))}
        </tbody>
      </ScrollableTable>
      {isUpdate && targetStale && (
        <details style={{ marginTop: 16 }}>
          <summary>Current saved action item</summary>
          <ScrollableTable
            label="Current saved action item"
            className="action-item-proposal-table"
          >
            <thead>
              <tr>
                <th>Field</th>
                <th>Current value</th>
              </tr>
            </thead>
            <tbody role="rowgroup">
              {FIELDS.map(([field, label]) => (
                <tr key={field} role="row">
                  <th scope="row" role="rowheader">
                    {label}
                  </th>
                  <td role="cell" data-label="Current value">
                    <TaskValue item={proposal.current_target} field={field} />
                  </td>
                </tr>
              ))}
            </tbody>
          </ScrollableTable>
        </details>
      )}
    </>
  );
}
