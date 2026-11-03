export function ResetViewButton({ onReset, disabled = false }: { onReset: () => void; disabled?: boolean }) {
  return <button className="btn" type="button" disabled={disabled} onClick={onReset}>Reset view</button>;
}
