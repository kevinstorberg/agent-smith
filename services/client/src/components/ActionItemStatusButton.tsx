import type { ActionItemRow } from '../api';
import { ActionItemIcon } from './ActionItemIcon';

export function ActionItemStatusButton({
  item,
  disabled,
  small = false,
  iconOnly = false,
  onChange,
  noun = 'action item',
}: {
  item: Pick<ActionItemRow, 'title' | 'status'>;
  disabled?: boolean;
  small?: boolean;
  iconOnly?: boolean;
  onChange: () => void;
  noun?: string;
}) {
  const completing = item.status === 'open';
  const label = completing ? 'Complete' : 'Reopen';
  return (
    <button
      type="button"
      className={`btn${small ? ' btn-sm' : ''}${completing ? ' btn-success' : ''}${iconOnly ? ' action-item-icon-button' : ''}`}
      aria-label={`${label} ${item.title}`}
      title={iconOnly ? label : undefined}
      disabled={disabled}
      onKeyDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        if (!completing || confirm(`Complete ${noun} “${item.title}”?`))
          onChange();
      }}
    >
      {iconOnly ? (
        <ActionItemIcon name={completing ? 'complete' : 'reopen'} />
      ) : (
        label
      )}
    </button>
  );
}
