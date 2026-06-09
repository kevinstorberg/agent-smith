import type { CSSProperties } from 'react';

export interface ProjectCellProps {
  project: string | null;
}

export function ProjectCell({ project }: ProjectCellProps) {
  return (
    <div>
      {project ? (
        <span className="tag tag-project">{project}</span>
      ) : (
        <span style={{ color: 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>shared</span>
      )}
    </div>
  );
}

export interface EnabledToggleCellProps {
  enabled: boolean;
  onChange: () => void;
  label?: { on: string; off: string };
  accentColor?: string;
}

export function EnabledToggleCell({
  enabled,
  onChange,
  label = { on: 'On', off: 'Off' },
  accentColor = 'var(--success)',
}: EnabledToggleCellProps) {
  return (
    <div onClick={e => e.stopPropagation()}>
      <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
        <input
          type="checkbox"
          checked={enabled}
          onChange={onChange}
          style={{ accentColor, width: 16, height: 16 }}
        />
        <span style={{ color: enabled ? accentColor : 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>
          {enabled ? label.on : label.off}
        </span>
      </label>
    </div>
  );
}

export interface BadgeCellProps {
  items: string[];
  style?: CSSProperties;
}

export function BadgeCell({ items, style }: BadgeCellProps) {
  return (
    <div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {items.map(item => (
          <span key={item} className="tag" style={style}>
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

export interface DateCellProps {
  date: string | Date;
  format?: 'short' | 'long';
}

export function DateCell({ date, format = 'short' }: DateCellProps) {
  const dateObj = typeof date === 'string' ? new Date(date) : date;

  const formatted = format === 'short'
    ? dateObj.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : dateObj.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });

  return (
    <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-base)' }}>
      {formatted}
    </div>
  );
}

export interface VersionCellProps {
  version: number;
}

export function VersionCell({ version }: VersionCellProps) {
  return (
    <div style={{ fontFamily: 'var(--mono)', fontSize: 'var(--font-base)' }}>
      v{version}
    </div>
  );
}
