import { ToggleButton } from './ToggleButton';
interface Props {
  name: string;
  starred: boolean;
  disabled?: boolean;
  onClick: () => void;
}

export function ProfileStar({ name, starred, disabled, onClick }: Props) {
  return (
    <ToggleButton
      className="profile-star"
      label={`${starred ? 'Unstar' : 'Star'} ${name}`}
      pressed={starred}
      disabled={disabled}
      onClick={onClick}
    >
      <span aria-hidden="true">{starred ? '★' : '☆'}</span>
    </ToggleButton>
  );
}
