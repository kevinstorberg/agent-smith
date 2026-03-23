interface TabNavProps {
  tabs: string[];
  active: string;
  onChange: (tab: string) => void;
}

export function TabNav({ tabs, active, onChange }: TabNavProps) {
  return (
    <div className="tab-nav">
      {tabs.map((tab) => (
        <button
          key={tab}
          className={tab === active ? 'active' : ''}
          onClick={() => onChange(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}
