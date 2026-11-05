import type {
  ChangeEventHandler,
  ComponentPropsWithoutRef,
  ReactNode,
} from 'react';

type FilterCheckboxProps = Omit<
  ComponentPropsWithoutRef<'input'>,
  'type' | 'className' | 'children' | 'checked' | 'defaultChecked' | 'onChange'
> & {
  children: ReactNode;
  checked: boolean;
  onChange: ChangeEventHandler<HTMLInputElement>;
};

export function FilterCheckbox({ children, ...props }: FilterCheckboxProps) {
  return (
    <label className="checkbox-label filter-checkbox">
      <input {...props} className="form-checkbox" type="checkbox" />
      {children}
    </label>
  );
}
