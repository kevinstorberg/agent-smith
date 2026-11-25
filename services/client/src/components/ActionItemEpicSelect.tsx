import { useId, useMemo, useRef, useState } from 'react';
import type { ActionItemEpic } from '../api';
import { epicOptionLabel } from '../utils/actionItemEpics';
import { ActionDisclosure } from './ActionDisclosure';
import './actionItemEpicSelect.css';

interface EpicChoice {
  value: string;
  label: string;
}
interface EpicSelectProps {
  label: string;
  value: string;
  epics: ActionItemEpic[];
  onChange: (value: string) => void;
  defaultLabel?: string;
  disabled?: boolean;
  autoFocus?: boolean;
  allowCreate?: boolean;
  retainedOption?: EpicChoice;
  ariaLabel?: string;
  ariaDescribedBy?: string;
  omitEpicId?: number;
}

function EpicChoices({
  value,
  epics,
  onChoose,
  defaultLabel,
  allowCreate,
  retainedOption,
  omitEpicId,
}: Required<
  Pick<EpicSelectProps, 'value' | 'epics' | 'defaultLabel' | 'allowCreate'>
> &
  Pick<EpicSelectProps, 'retainedOption' | 'omitEpicId'> & {
    onChoose: (value: string) => void;
  }) {
  const [query, setQuery] = useState('');
  const search = useRef<HTMLInputElement>(null);
  const results = useRef<HTMLUListElement>(null);
  const options = useMemo(
    () =>
      epics
        .filter((epic) => epic.id !== omitEpicId)
        .map((epic) => ({
          value: String(epic.id),
          label: epicOptionLabel(epic, epics),
        })),
    [epics, omitEpicId],
  );
  const matches = options.filter((option) =>
    option.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  const shown = matches.slice(0, 20);
  const focusResult = (index: number) => {
    results.current
      ?.querySelectorAll<HTMLButtonElement>('button')
      .item(index)
      ?.focus();
  };
  const choice = (option: EpicChoice) => (
    <button
      type="button"
      className="btn epic-choice"
      value={option.value}
      aria-current={value === option.value ? 'true' : undefined}
      onClick={() => onChoose(option.value)}
    >
      <span>{option.label}</span>
      {value === option.value && <span aria-hidden="true">✓</span>}
    </button>
  );

  return (
    <div className="epic-choices">
      <label>
        <span className="form-label">Find Epic</span>
        <input
          ref={search}
          className="input"
          autoFocus
          type="search"
          value={query}
          placeholder="Search Epic names…"
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === 'ArrowDown') {
              event.preventDefault();
              focusResult(0);
            }
          }}
        />
      </label>
      {query && (
        <button
          type="button"
          className="inline-clear"
          onClick={() => {
            setQuery('');
            search.current?.focus();
          }}
        >
          Clear Epic search
        </button>
      )}
      {choice({ value: '', label: defaultLabel })}
      {retainedOption && choice(retainedOption)}
      <p className="text-muted-sm epic-choice-count" role="status">
        {matches.length > 20
          ? `Showing 20 of ${matches.length} Epics. Refine your search.`
          : `${matches.length} ${matches.length === 1 ? 'Epic' : 'Epics'} found`}
      </p>
      {matches.length === 0 && (
        <p className="text-muted-sm">No matching Epics</p>
      )}
      <ul
        ref={results}
        className="epic-choice-results"
        onKeyDown={(event) => {
          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
          const buttons = Array.from(
            results.current?.querySelectorAll<HTMLButtonElement>('button') ??
              [],
          );
          const index = buttons.indexOf(
            document.activeElement as HTMLButtonElement,
          );
          if (index < 0) return;
          event.preventDefault();
          if (event.key === 'ArrowUp' && index === 0) search.current?.focus();
          else
            focusResult(
              Math.min(
                buttons.length - 1,
                index + (event.key === 'ArrowDown' ? 1 : -1),
              ),
            );
        }}
      >
        {shown.map((option) => (
          <li key={option.value}>{choice(option)}</li>
        ))}
      </ul>
      {allowCreate && choice({ value: 'new', label: 'New Epic…' })}
    </div>
  );
}

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
}: EpicSelectProps) {
  const selectionId = useId();
  const selected =
    value === ''
      ? defaultLabel
      : retainedOption?.value === value
        ? retainedOption.label
        : value === 'new' && allowCreate
          ? 'New Epic…'
          : epics.find((epic) => String(epic.id) === value);
  const title =
    typeof selected === 'string'
      ? selected
      : selected
        ? epicOptionLabel(selected, epics)
        : `Epic #${value} (unavailable)`;
  return (
    <div className="action-item-epic-select">
      <span className="form-label">{label}</span>
      <ActionDisclosure
        label={ariaLabel ?? label}
        ariaDescribedBy={[selectionId, ariaDescribedBy]
          .filter(Boolean)
          .join(' ')}
        autoFocus={autoFocus}
        disabled={disabled}
        triggerContent={
          <>
            <span id={selectionId}>{title}</span>
            <span aria-hidden="true">⌄</span>
          </>
        }
      >
        {(close, open) =>
          open && (
            <EpicChoices
              value={value}
              epics={epics}
              defaultLabel={defaultLabel}
              allowCreate={allowCreate}
              retainedOption={retainedOption}
              omitEpicId={omitEpicId}
              onChoose={(next) => {
                if (disabled) return;
                close();
                if (next !== value || next === retainedOption?.value)
                  onChange(next);
              }}
            />
          )
        }
      </ActionDisclosure>
    </div>
  );
}
