import type { ReactNode } from 'react';

export interface FilterBarProps {
  nameValue: string;
  projectValue?: string;
  onNameChange: (value: string) => void;
  onProjectChange?: (value: string) => void;
  nameLabel?: string;
  projectLabel?: string;
  namePlaceholder?: string;
  projectPlaceholder?: string;
  children?: ReactNode;
  className?: string;
  disabled?: boolean;
}

export function FilterBar({
  nameValue,
  projectValue,
  onNameChange,
  onProjectChange,
  nameLabel = 'Search',
  projectLabel = 'Project scope',
  namePlaceholder = 'Search by name...',
  projectPlaceholder = 'Filter by project...',
  children,
  className = '',
  disabled = false,
}: FilterBarProps) {
  return (
    <div className={`filters resource-controls ${className}`}>
      <label className="filter-search">
        <span className="form-label">{nameLabel}</span>
        <input
          placeholder={namePlaceholder}
          maxLength={1000}
          disabled={disabled}
          value={nameValue}
          onChange={e => { if (!disabled) onNameChange(e.target.value); }}
        />
      </label>
      {onProjectChange && <label className="filter-project">
        <span className="form-label">{projectLabel}</span>
        <input
          placeholder={projectPlaceholder}
          disabled={disabled}
          value={projectValue ?? ''}
          onChange={e => { if (!disabled) onProjectChange(e.target.value); }}
        />
      </label>}
      {children}
    </div>
  );
}
