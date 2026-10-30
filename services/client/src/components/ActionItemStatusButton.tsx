import type { ActionItemRow } from '../api';

export function ActionItemStatusButton({ item, disabled, small = false, onChange }: {
  item: Pick<ActionItemRow, 'title' | 'status'>;
  disabled?: boolean;
  small?: boolean;
  onChange: () => void;
}) {
  const completing = item.status === 'open';
  const label = completing ? 'Complete' : 'Reopen';
  return <button type="button" className={`btn${small ? ' btn-sm' : ''}${completing ? ' btn-success' : ''}`}
    aria-label={`${label} ${item.title}`} disabled={disabled}
    onKeyDown={event => event.stopPropagation()}
    onClick={event => {
      event.stopPropagation();
      if (!completing || confirm(`Complete action item “${item.title}”?`)) onChange();
    }}>{label}</button>;
}
