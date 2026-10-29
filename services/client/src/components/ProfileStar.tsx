interface Props {
  name: string;
  starred: boolean;
  disabled?: boolean;
  onClick: () => void;
}

export function ProfileStar({ name, starred, disabled, onClick }: Props) {
  return <button className="btn btn-sm" aria-label={`${starred ? 'Unstar' : 'Star'} ${name}`} aria-pressed={starred}
    disabled={disabled} style={{ color: starred ? 'var(--warning)' : 'var(--text-muted)' }}
    onKeyDown={event => event.stopPropagation()}
    onClick={event => { event.stopPropagation(); onClick(); }}>
    {starred ? '★' : '☆'}
  </button>;
}
