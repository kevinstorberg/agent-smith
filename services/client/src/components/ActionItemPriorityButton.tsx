import type { ActionItemRow } from '../api';
import { ToggleButton } from './ToggleButton';

export function ActionItemPriorityButton({
  item,
  disabled,
  onClick,
}: {
  item: ActionItemRow;
  disabled: boolean;
  onClick: () => void;
}) {
  const marked = Boolean(item.is_priority);
  return (
    <ToggleButton
      className="btn btn-sm"
      pressed={marked}
      disabled={disabled}
      label={
        marked
          ? `Remove Priority from ${item.title}`
          : `Mark ${item.title} as Priority`
      }
      onClick={onClick}
    >
      {marked ? 'Remove Priority' : 'Mark as Priority'}
    </ToggleButton>
  );
}
