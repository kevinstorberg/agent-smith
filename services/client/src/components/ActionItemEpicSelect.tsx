import type { ActionItemEpic } from '../api';
import { epicOptionLabel } from '../utils/actionItemEpics';

export function ActionItemEpicSelect({
  label,
  value,
  epics,
  onChange,
  defaultLabel = 'No Epic',
  disabled = false,
  autoFocus = false,
  allowCreate = false,
  retainedOption,
  ariaLabel,
  ariaDescribedBy,
  omitEpicId,
}: {
  label: string;
  value: string;
  epics: ActionItemEpic[];
  onChange: (value: string) => void;
  defaultLabel?: string;
  disabled?: boolean;
  autoFocus?: boolean;
  allowCreate?: boolean;
  retainedOption?: { value: string; label: string };
  ariaLabel?: string;
  ariaDescribedBy?: string;
  omitEpicId?: number;
}) {
  return (
    <label>
      <span className="form-label">{label}</span>
      <select
        className="input"
        value={value}
        disabled={disabled}
        autoFocus={autoFocus}
        aria-label={ariaLabel}
        aria-describedby={ariaDescribedBy}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{defaultLabel}</option>
        {retainedOption && (
          <option value={retainedOption.value}>{retainedOption.label}</option>
        )}
        {epics
          .filter((epic) => epic.id !== omitEpicId)
          .map((epic) => (
            <option key={epic.id} value={epic.id}>
              {epicOptionLabel(epic, epics)}
            </option>
          ))}
        {allowCreate && <option value="new">New Epic…</option>}
      </select>
    </label>
  );
}
