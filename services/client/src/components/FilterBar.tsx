import type { ReactNode } from 'react';
import { ResetViewButton } from './ResetViewButton';

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
  onReset?: () => void;
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
  onReset,
}: FilterBarProps) {
  return (
    <div className={`filters resource-controls ${className}`}>
      <label className="filter-search">
        <span className="form-label">{nameLabel}</span>
        <input
          placeholder={namePlaceholder}
          maxLength={1000}
          value={nameValue}
          onChange={e => onNameChange(e.target.value)}
        />
      </label>
      {onProjectChange && <label className="filter-project">
        <span className="form-label">{projectLabel}</span>
        <input
          placeholder={projectPlaceholder}
          value={projectValue ?? ''}
          onChange={e => onProjectChange(e.target.value)}
        />
      </label>}
      {children}
      {onReset && <ResetViewButton onReset={onReset} />}
    </div>
  );
}
