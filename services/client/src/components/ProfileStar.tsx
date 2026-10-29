interface Props {
  name: string;
  starred: boolean;
  disabled?: boolean;
  onClick: () => void;
}

export function ProfileStar({ name, starred, disabled, onClick }: Props) {
  return <button className="profile-star" aria-label={`${starred ? 'Unstar' : 'Star'} ${name}`} aria-pressed={starred}
    disabled={disabled}
    onKeyDown={event => event.stopPropagation()}
    onClick={event => { event.stopPropagation(); onClick(); }}>
    <span aria-hidden="true">{starred ? '★' : '☆'}</span>
  </button>;
}
