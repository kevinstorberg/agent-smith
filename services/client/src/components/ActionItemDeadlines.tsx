import { useEffect, useId, useState } from 'react';
import { DateCell } from './table';
import {
  changeDeadline,
  deadlineValue,
  MAX_DUE_WINDOW_HOURS,
} from '../utils/actionItemDeadlines';
import type { DeadlineDraft } from '../utils/actionItemDeadlines';
import './actionItemDeadlines.css';

export function ActionItemDueDate({ value }: { value?: string | null }) {
  if (!value) return null;
  return (
    <div className="action-item-due">
      <span>Due </span>
      <DateCell date={value} format="long" />
    </div>
  );
}

export function ActionItemDeadlineField({
  value,
  onChange,
  disabled,
}: {
  value: DeadlineDraft;
  onChange: (value: DeadlineDraft) => void;
  disabled: boolean;
}) {
  const id = useId();
  let instant: string | null = null;
  let error: string | null = null;
  try {
    instant = deadlineValue(value);
  } catch (failure) {
    error = failure instanceof Error ? failure.message : String(failure);
  }
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const offset = instant
    ? Intl.DateTimeFormat('en-US', { timeZoneName: 'shortOffset' })
        .formatToParts(new Date(instant))
        .find((part) => part.type === 'timeZoneName')?.value
    : null;
  return (
    <section className="action-deadline-field">
      <label className="form-label" htmlFor={id}>
        Due date and time
      </label>
      <div className="action-deadline-input">
        <input
          id={id}
          className="input"
          type="datetime-local"
          step={60}
          value={value.local}
          disabled={disabled}
          aria-invalid={Boolean(error)}
          aria-describedby={`${id}-help`}
          onChange={(event) =>
            onChange(changeDeadline(value, event.target.value))
          }
        />
        {(value.local || value.original) && (
          <button
            className="btn"
            disabled={disabled}
            type="button"
            onClick={() => onChange(changeDeadline(value, ''))}
          >
            Clear deadline
          </button>
        )}
      </div>
      <p id={`${id}-help`} className="text-muted-sm">
        Times use your local time zone ({zone}).
      </p>
      {instant && (
        <div className="text-muted-sm" role="status">
          Selected deadline: <DateCell date={instant} format="long" /> {offset}
        </div>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

export function ActionItemDeadlineWindow({
  hours,
  onChange,
  disabled,
}: {
  hours: number | null;
  onChange: (hours: number | null) => void;
  disabled: boolean;
}) {
  const id = useId();
  const [draft, setDraft] = useState(String(hours ?? 24));
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setDraft(String(hours ?? 24));
    setError(null);
  }, [hours]);
  function validHours(value: string) {
    const number = /^\d+$/.test(value) ? Number(value) : NaN;
    return Number.isSafeInteger(number) &&
      number >= 1 &&
      number <= MAX_DUE_WINDOW_HOURS
      ? number
      : null;
  }
  return (
    <section className="action-deadline-window" aria-label="Deadline filter">
      <label className="filter-checkbox">
        <input
          type="checkbox"
          checked={hours !== null}
          disabled={disabled}
          onChange={(event) => {
            setError(null);
            onChange(event.target.checked ? 24 : null);
          }}
        />
        Deadline window
      </label>
      {hours !== null && (
        <>
          <div className="action-deadline-window-inputs">
            <label htmlFor={`${id}-range`}>Upcoming hours</label>
            <input
              id={`${id}-range`}
              type="range"
              min={1}
              max={MAX_DUE_WINDOW_HOURS}
              step={1}
              value={hours}
              disabled={disabled}
              onChange={(event) => {
                const number = validHours(event.target.value);
                if (number !== null) {
                  setError(null);
                  onChange(number);
                }
              }}
            />
            <label htmlFor={`${id}-hours`}>Hours</label>
            <input
              id={`${id}-hours`}
              className="input"
              type="number"
              min={1}
              max={MAX_DUE_WINDOW_HOURS}
              step={1}
              value={draft}
              disabled={disabled}
              onChange={(event) => {
                setDraft(event.target.value);
                const number = validHours(event.target.value);
                if (number !== null) {
                  setError(null);
                  onChange(number);
                }
              }}
              onBlur={() => {
                if (validHours(draft) === null) {
                  setDraft(String(hours));
                  setError(
                    `Enter a whole number from 1 through ${MAX_DUE_WINDOW_HOURS}. The current window remains ${hours} hours.`,
                  );
                }
              }}
            />
          </div>
          <p className="text-muted-sm">
            Past deadlines and deadlines in the next {hours} hours; status,
            project and tags still apply.
          </p>
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
