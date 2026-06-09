export interface FilterBarProps {
  nameValue: string;
  projectValue: string;
  onNameChange: (value: string) => void;
  onProjectChange: (value: string) => void;
  namePlaceholder?: string;
  projectPlaceholder?: string;
}

export function FilterBar({
  nameValue,
  projectValue,
  onNameChange,
  onProjectChange,
  namePlaceholder = 'Search by name...',
  projectPlaceholder = 'Filter by project...',
}: FilterBarProps) {
  return (
    <div className="filters" style={{ marginBottom: 12 }}>
      <input
        placeholder={namePlaceholder}
        value={nameValue}
        onChange={e => onNameChange(e.target.value)}
        style={{ maxWidth: 260 }}
      />
      <input
        placeholder={projectPlaceholder}
        value={projectValue}
        onChange={e => onProjectChange(e.target.value)}
        style={{ maxWidth: 220 }}
      />
    </div>
  );
}
