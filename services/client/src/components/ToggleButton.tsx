import type { ReactNode } from 'react';

export function ToggleButton({
  label,
  pressed,
  disabled,
  onClick,
  className,
  children,
}: {
  label: string;
  pressed: boolean;
  disabled?: boolean;
  onClick: () => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className={className}
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
      onKeyDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
    >
      {children}
    </button>
  );
}
